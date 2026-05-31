"""
Receiver streaming pipeline.
Writes each decoded window to disk immediately — never buffers all windows in RAM.
Progress logged every window.
Memory peak: ~200MB regardless of file size.
"""
from __future__ import annotations
import logging
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from common import state_writer
from common.config import (DEFAULT_PORT, DEFAULT_ADDRESS, QUARANTINE_DIR,
                            STORAGE_DIR, WINDOWS_TMP, DEFAULT_CHUNK_SIZE)
from common.models import TransferManifest, TransferProgress
from receiver.m13_receiver import Receiver
from receiver.m14_validator import validate_manifest, validate_packet_dict
from receiver.m16_pooler import Pooler
from receiver.m17_fountain_decoder import FountainDecoder
from receiver.m18_rs_decoder import recover as rs_recover
from receiver.m19_merkle_verifier import simple_verify
from receiver.m20_window_writer import write_window
from receiver.m21_assembler import assemble
from receiver.m22_verifier import verify_file
from receiver.m23_decompress import decompress
from receiver.m24_quarantine import TransferRecord, TransferState
from receiver.m25_storage import store
from sender.m11_serializer import deserialize_manifest, deserialize_packet
from common.models import EncodedPacket

logger = logging.getLogger(__name__)


def run_receiver(bind_addr: str = DEFAULT_ADDRESS,
                 port: int = DEFAULT_PORT,
                 storage_dir: str = STORAGE_DIR,
                 timeout_s: float = 300.0) -> bool:
    """
    Run receiver until transfer completes or timeout.
    Returns True on successful file delivery.
    """
    for d in [QUARANTINE_DIR, STORAGE_DIR, WINDOWS_TMP]:
        Path(d).mkdir(parents=True, exist_ok=True)

    recv   = Receiver(bind_addr, port)
    pooler = Pooler()
    fdec   = FountainDecoder()

    # Thread pool for non-blocking decoding
    executor = ThreadPoolExecutor(max_workers=4)
    # Lock for protecting shared receiver state
    state_lock = threading.Lock()

    manifest    : TransferManifest | None = None
    record      : TransferRecord  | None = None
    window_files: dict[int, Path]         = {}
    window_padding: dict[int, int]       = {}
    window_data_chunks: dict[int, int]   = {}
    progress    : TransferProgress | None = None
    last_packet  = time.time()
    t_start      = time.time()

    # Track stats for monitoring
    m_stats = {
        "fountain_recovered_by_window": {}, # wid -> count
        "rs_recovered_by_window": {},      # wid -> count
        "failed_chunks_by_window": {},     # wid -> count
        "last_decode_attempt_time": {}     # wid -> float
    }

    logger.info(f"Receiver listening on {bind_addr}:{port}")

    try:
        while True:
            # Global timeout
            if time.time() - t_start > timeout_s:
                msg = f"Global timeout after {timeout_s}s"
                logger.error(msg)
                state_writer.add_error(msg)
                state_writer.set_overall_state("FAILED")
                return False

            raw = recv.recv_one(timeout=0.1)
            if raw is None:
                # Check for window timeouts if we have a manifest
                if manifest and time.time() - last_packet > 10:
                    _check_decode_ready(manifest, pooler, fdec, window_files,
                                        window_padding, window_data_chunks, progress, m_stats, t_start,
                                        executor, state_lock, force=True)

                # IMPORTANT: Completion check must happen even if raw is None
                if manifest:
                    with state_lock:
                        done = len([p for p in window_files.values() if p is not None])
                    if done == manifest.total_windows:
                        return _finish(manifest, window_files, storage_dir, progress, record, m_stats, t_start)
                continue

            last_packet = time.time()

            # Try manifest first
            if manifest is None:
                m = deserialize_manifest(raw)
                if m is not None:
                    ok, reason = validate_manifest(m)
                    if not ok:
                        logger.warning(f"Manifest rejected: {reason}")
                        continue
                    manifest  = m
                    record    = TransferRecord(m.transfer_id)
                    progress  = TransferProgress(m.transfer_id, m.file_name,
                                                 m.total_windows)
                    state_writer.set_overall_state("RECEIVING")
                    logger.info(f"Transfer started: {m.file_name} "
                                f"({m.file_size/1024**2:.1f}MB compressed, "
                                f"{m.total_windows} windows)")
                    continue

            # Try packet
            pkt_dict = deserialize_packet(raw)
            if pkt_dict is None:
                continue

            ok, reason = validate_packet_dict(pkt_dict, manifest, t_start)
            if not ok:
                continue

            # Reconstruct EncodedPacket
            try:
                pkt = EncodedPacket(
                    packet_id          = pkt_dict["packet_id"],
                    pass_id            = pkt_dict["pass_id"],
                    seed               = pkt_dict["seed"],
                    degree             = pkt_dict["degree"],
                    chunk_ids          = pkt_dict["chunk_ids"],
                    data               = pkt_dict["data"], # already bytes
                    source_chunk_count = pkt_dict["K_prime"],
                )
            except (KeyError, ValueError):
                continue

            # FIX F: Disk-backed window storage
            pooler.add(manifest.transfer_id, pkt_dict["window_id"], pkt)
            window_padding[pkt_dict["window_id"]] = pkt_dict["padding_length"]
            window_data_chunks[pkt_dict["window_id"]] = pkt_dict["data_chunk_count"]
            if progress:
                progress.total_packets_rx += 1

            # Check decode readiness for this window
            wid     = pkt_dict["window_id"]
            K_prime = pkt.source_chunk_count

            if pooler.is_ready(manifest.transfer_id, wid, K_prime):
                now = time.time()
                with state_lock:
                    last_attempt = m_stats["last_decode_attempt_time"].get(wid, 0)

                # Throttle: only decode if it's the first time, OR it's been 5 seconds
                # This prevents spinning CPU on every packet when we're close to recovery
                if last_attempt == 0 or (now - last_attempt) > 5.0:
                    with state_lock:
                        m_stats["last_decode_attempt_time"][wid] = now

                    # Submit to background executor
                    executor.submit(_decode_and_store, manifest, wid, K_prime, pooler, fdec,
                                   window_files, window_padding, window_data_chunks,
                                   progress, m_stats, t_start, state_lock)

            # Check if all windows done
            with state_lock:
                done = len([p for p in window_files.values() if p is not None])
            if manifest and done == manifest.total_windows:
                return _finish(manifest, window_files, storage_dir, progress, record, m_stats, t_start)
    except Exception as e:
        msg = f"Fatal receiver error: {e}"
        logger.error(msg)
        state_writer.add_error(msg)
        state_writer.set_overall_state("FAILED")
        return False
    finally:
        recv.close()
        executor.shutdown(wait=False)


def _decode_and_store(manifest, wid, K_prime, pooler, fdec,
                       window_files, window_padding, window_data_chunks,
                       progress, m_stats, t_start, state_lock):
    """FIX F: Decode one window, verify, write to disk, free RAM."""
    with state_lock:
        if wid in window_files:
            return   # already done

    pool   = pooler.get_pool(manifest.transfer_id, wid)
    result = fdec.decode(pool, K_prime, manifest.chunk_size)

    # RS recovery
    missing_before_rs = sum(1 for c in result.chunks if c is None)

    recovered = rs_recover(result.chunks, manifest, manifest.chunk_size)
    missing_after_rs = sum(1 for c in recovered if c is None)

    # FIX H: Use window_chunk_counts from manifest if available
    # Fallback to window_data_chunks dict (populated from packets) if not in manifest
    if manifest.window_chunk_counts and wid < len(manifest.window_chunk_counts):
        data_count = manifest.window_chunk_counts[wid]
    else:
        data_count = window_data_chunks.get(wid, K_prime - manifest.rs_k)
    padding       = window_padding.get(wid, 0)

    # Update stats for THIS attempt (per-window)
    with state_lock:
        m_stats["fountain_recovered_by_window"][wid] = result.recovered_count
        m_stats["rs_recovered_by_window"][wid] = (missing_before_rs - missing_after_rs)
        m_stats["failed_chunks_by_window"][wid] = sum(1 for c in recovered[:data_count] if c is None)

    # FIX F: When each window is decoded and verified, write to disk:
    path = write_window(wid, recovered, padding, data_count,
                        manifest.chunk_size, Path(WINDOWS_TMP))

    with state_lock:
        if path is None:
            logger.debug(f"Window {wid} decode incomplete, waiting for more packets")
            # Do NOT clear pooler, DO NOT mark in window_files
        else:
            window_files[wid] = path
            if progress:
                progress.completed_windows += 1
                progress.log(logger)
            pooler.clear_window(manifest.transfer_id, wid)
        
        # Always update UI with aggregated stats
        f_total = sum(m_stats["fountain_recovered_by_window"].values())
        r_total = sum(m_stats["rs_recovered_by_window"].values())
        e_total = sum(m_stats["failed_chunks_by_window"].values())

        win_done = len([p for p in window_files.values() if p is not None])
    # If all windows are decoded but not yet assembled, we are in 'verifying' state
    status = "verifying" if (manifest and win_done == manifest.total_windows) else "decoding"

    state_writer.update_receiver(
        windows_decoded=win_done,
        total_packets_rx=progress.total_packets_rx if progress else 0,
        fountain_recovered_chunks=f_total,
        rs_recovered_chunks=r_total,
        failed_chunks=e_total,
        elapsed_s=time.time() - t_start,
        status=status,
    )
    
    del pool, result, recovered


def _check_decode_ready(manifest, pooler, fdec, window_files, window_padding, window_data_chunks, progress, m_stats, t_start, executor, state_lock,
                         force=False):
    """Check all windows that might be ready to decode."""
    for wid in range(manifest.total_windows):
        with state_lock:
            if wid in window_files:
                continue

        # Don't try to decode windows that have no packets yet
        if pooler.count(manifest.transfer_id, wid) == 0:
            continue

        # FIX H: Use window_chunk_counts from manifest if available
        if manifest.window_chunk_counts and wid < len(manifest.window_chunk_counts):
            win_data_chunks = manifest.window_chunk_counts[wid]
        else:
            # Fallback: recalculate (though this may be inaccurate for last window)
            if wid < manifest.total_windows - 1:
                win_data_chunks = manifest.window_size_bytes // manifest.chunk_size
            else:
                win_data_chunks = manifest.total_chunks - (manifest.total_windows - 1) * (manifest.window_size_bytes // manifest.chunk_size)

        # Each block of RS_DATA_PER_BLOCK chunks gets manifest.rs_k parity chunks
        rs_data_per_block = manifest.rs_n - manifest.rs_k
        if rs_data_per_block > 0:
            num_blocks = (win_data_chunks + rs_data_per_block - 1) // rs_data_per_block
            win_rs_chunks = num_blocks * manifest.rs_k
        else:
            win_rs_chunks = 0

        K_prime = win_data_chunks + win_rs_chunks

        if force or pooler.is_ready(manifest.transfer_id, wid, K_prime):
            now = time.time()
            with state_lock:
                last_attempt = m_stats["last_decode_attempt_time"].get(wid, 0)

            # Even if forced (timeout), don't spam the background worker more than once per 5s
            if last_attempt == 0 or (now - last_attempt) > 5.0:
                with state_lock:
                    m_stats["last_decode_attempt_time"][wid] = now
                executor.submit(_decode_and_store, manifest, wid, K_prime, pooler, fdec,
                                  window_files, window_padding, window_data_chunks, progress, m_stats, t_start, state_lock)


def _finish(manifest, window_files, storage_dir, progress, record, m_stats, t_start) -> bool:
    """Assemble windows → verify → decompress → store."""
    logger.info("All windows received — assembling file")
    
    f_total = sum(m_stats["fountain_recovered_by_window"].values())
    r_total = sum(m_stats["rs_recovered_by_window"].values())
    e_total = sum(m_stats["failed_chunks_by_window"].values())

    state_writer.set_overall_state("VERIFYING")
    state_writer.update_receiver(
        windows_decoded=len([p for p in window_files.values() if p is not None]),
        total_packets_rx=progress.total_packets_rx if progress else 0,
        fountain_recovered_chunks=f_total,
        rs_recovered_chunks=r_total,
        failed_chunks=e_total,
        elapsed_s=time.time() - t_start,
        status="verifying",
    )

    if any(p is None for p in window_files.values()):
        msg = "Some windows failed — transfer incomplete"
        logger.error(msg)
        state_writer.add_error(msg)
        state_writer.set_overall_state("FAILED")
        return False

    # Assemble compressed file
    compressed_out = Path(QUARANTINE_DIR) / f"{manifest.transfer_id[:8]}_compressed"
    # FIX F: When all windows complete — stream-assemble from temp files:
    ok = assemble(window_files, manifest.total_windows,
                  compressed_out, manifest.file_sha256)
    if not ok:
        msg = "File assembly failed"
        state_writer.add_error(msg)
        state_writer.set_overall_state("FAILED")
        return False

    # Verify compressed file
    if not verify_file(compressed_out, manifest):
        msg = "Compressed file verification failed"
        state_writer.add_error(msg)
        state_writer.set_overall_state("FAILED")
        return False

    # Decompress
    final_out = Path(QUARANTINE_DIR) / manifest.file_name
    ok = decompress(compressed_out, final_out,
                    manifest.compression_algorithm, manifest.original_sha256)
    if not ok:
        msg = "Decompression failed"
        state_writer.add_error(msg)
        state_writer.set_overall_state("FAILED")
        return False

    # Store
    stats = {"windows": manifest.total_windows,
             "packets": progress.total_packets_rx if progress else 0}
    if store(final_out, storage_dir, manifest, stats):
        dest = Path(storage_dir) / manifest.file_name
        state_writer.update_receiver(
            windows_decoded=len([p for p in window_files.values() if p is not None]),
            total_packets_rx=progress.total_packets_rx if progress else 0,
            fountain_recovered_chunks=f_total,
            rs_recovered_chunks=r_total,
            failed_chunks=e_total,
            elapsed_s=time.time() - t_start,
            status="accepted",
            sha256_match=True,
            storage_path=dest
        )
        state_writer.set_overall_state("ACCEPTED")
    else:
        msg = "Storage failed"
        state_writer.add_error(msg)
        state_writer.set_overall_state("FAILED")
        return False

    total_time = time.time() - (progress.start_time if progress else time.time())
    logger.info(f"=== TRANSFER COMPLETE: {manifest.file_name} "
                f"in {total_time:.1f}s ===")
    return True
