"""
Sender streaming pipeline.
One window at a time — never buffers more than one window's packets in RAM.
Streaming compression and Merkle root — safe for 10GB+ files.
"""
from __future__ import annotations
import logging
import os
import tempfile
import time
from pathlib import Path
from common import state_writer
from common.config import DEFAULT_CHUNK_SIZE, QUARANTINE_DIR, get_chunk_size
from common.models import TransferProgress
from sender.m0_compress import compress_file
from sender.m1_manifest import generate_manifest
from sender.m2_windowing import compute_windows, read_window
from sender.m3_chunker import chunk_window
from sender.m5_rs_encoder import encode_rs, RSConfig
from sender.m6_profile import select_profile, select_window_size
from sender.m7_fountain_encoder import encode_window
from sender.m9_interleaver import interleave_multipass
from sender.m10_packet_builder import attach_security
from sender.m11_serializer import serialize_manifest, serialize_packet
from sender.m12_transmitter import Transmitter

logger = logging.getLogger(__name__)

SHARED_KEY = b"x" * 32   # 32-byte key — replace with env var in production


def run_sender(file_path: str, remote_addr: tuple,
               criticality: str = "standard",
               packets_per_second: int = 10000) -> bool:
    """
    Stream file through the diode pipeline.
    Returns True on success.
    """
    t_start = time.time()
    logger.info(f"=== SENDER START: {file_path} → {remote_addr} ===")

    file_size  = os.path.getsize(file_path)
    profile    = select_profile(file_size, criticality)
    rs_config  = RSConfig(n=profile.rs_n, k=profile.rs_k)

    chunk_size = get_chunk_size(file_size)

    logger.info(
        f"Selected chunk size: {chunk_size} bytes "
        f"for file size {file_size/1024**2:.1f}MB"
    )

    # Step 2: Compress
    with tempfile.NamedTemporaryFile(suffix=".lz4", delete=False) as tmp:
        compressed_path = tmp.name

    compress_result = compress_file(file_path, compressed_path)
    compressed_size = compress_result.compressed_size

    # IMPORTANT:
    # Windowing must be based on the ACTUAL file being transmitted.
    win_size = select_window_size(compressed_size)

    # Step 3: Windows
    windows   = compute_windows(compressed_size, win_size)
    n_windows = len(windows)

    # Step 4: Manifest
    original_file_name = os.path.basename(file_path)
    manifest       = generate_manifest(original_file_name, compressed_path, compress_result,
                                       n_windows, win_size, profile, criticality, chunk_size=chunk_size)
    manifest_bytes = serialize_manifest(manifest)

    # MONITORING
    state_writer.init_state(
        transfer_id=manifest.transfer_id,
        file_name=original_file_name,
        total_windows=n_windows,
        criticality=criticality,
        file_path=file_path,
        original_size_mb=file_size / 1024**2,
        compression_algorithm=compress_result.algorithm,
    )
    state_writer.update_sender(
        windows_sent=0,
        total_packets_sent=0,
        bytes_transmitted_mb=0,
        compressed_size_mb=compress_result.compressed_size / 1024**2,
        compression_ratio=compress_result.compression_ratio,
        elapsed_s=0,
        eta_str="calculating...",
        status="sending",
    )

    # Step 5: Transmitter
    tx = Transmitter(packets_per_second)
    total_packets_sent = 0
    total_bytes_sent = 0

    # Step 6: Send manifest
    for _ in range(profile.header_redundancy):
        tx.send_raw(remote_addr, manifest_bytes)
        total_packets_sent += 1
        total_bytes_sent += len(manifest_bytes)
    logger.info(f"Manifest sent ×{profile.header_redundancy}")

    # FIX E: One window at a time
    progress = TransferProgress(manifest.transfer_id,
                                os.path.basename(file_path), n_windows)

    for window in windows:
        t_win = time.time()

        # Read ONE window
        window_data = read_window(Path(compressed_path), window)

        # Chunk with global ID offset
        chunk_id_offset = window.start_byte // chunk_size
        chunk_result    = chunk_window(window_data, chunk_size,
                                       chunk_id_offset)
        # DEBUG
        logger.info(
            f"WINDOW {window.window_id}: "
            f"bytes={len(window_data)} "
            f"chunks={chunk_result.chunk_count} "
            f"padding={chunk_result.padding_length}"
)

        # RS encode
        state_writer.update_sender(
            windows_sent=progress.completed_windows,
            total_packets_sent=total_packets_sent,
            bytes_transmitted_mb=total_bytes_sent / 1024**2,
            compressed_size_mb=compress_result.compressed_size / 1024**2,
            compression_ratio=compress_result.compression_ratio,
            elapsed_s=time.time() - t_start,
            eta_str=progress.eta_str,
            status="encoding_rs",
        )
        chunks_with_parity = encode_rs(chunk_result.chunks, rs_config)

        # Fountain encode (all passes)
        encoded_pkts = encode_window(
            manifest.transfer_id, window.window_id,
            chunks_with_parity, profile.num_passes, profile.overhead_ratio)

        # Split by pass for interleaving
        passes: dict[int, list] = {}
        for p in encoded_pkts:
            passes.setdefault(p.pass_id, []).append(p)
        passes_list = [passes.get(i, []) for i in range(profile.num_passes)]
        interleaved = interleave_multipass(passes_list, profile.interleave_depth)

        # Serialize and transmit immediately (streamed)
        for pkt in interleaved:
            pkt_dict  = attach_security(pkt, manifest.transfer_id,
                                        window.window_id,
                                        chunk_result.padding_length,
                                        chunk_result.chunk_count,
                                        SHARED_KEY)
            pkt_bytes = serialize_packet(pkt_dict)
            tx.send_raw(remote_addr, pkt_bytes)
            total_packets_sent += 1
            total_bytes_sent += len(pkt_bytes)

        # FIX E: FREE MEMORY — critical for GB scale
        del window_data, chunk_result, chunks_with_parity
        del encoded_pkts, passes, passes_list, interleaved

        # Progress
        progress.completed_windows += 1
        elapsed = time.time() - t_win
        logger.info(f"Window {window.window_id+1}/{n_windows} "
                    f"({progress.pct:.1f}%) sent in {elapsed:.1f}s "
                    f"| ETA: {progress.eta_str}")

        # MONITORING
        state_writer.update_sender(
            windows_sent=progress.completed_windows,
            total_packets_sent=total_packets_sent,
            bytes_transmitted_mb=total_bytes_sent / 1024**2,
            compressed_size_mb=compress_result.compressed_size / 1024**2,
            compression_ratio=compress_result.compression_ratio,
            elapsed_s=time.time() - t_start,
            eta_str=progress.eta_str,
            status="sending",
        )

    # Footer
    footer = b"DIODE_TRANSFER_END"
    for _ in range(3):
        tx.send_raw(remote_addr, footer)
        total_packets_sent += 1
        total_bytes_sent += len(footer)

    tx.close()
    os.remove(compressed_path)

    # MONITORING
    state_writer.update_sender(
        windows_sent=progress.completed_windows,
        total_packets_sent=total_packets_sent,
        bytes_transmitted_mb=total_bytes_sent / 1024**2,
        compressed_size_mb=compress_result.compressed_size / 1024**2,
        compression_ratio=compress_result.compression_ratio,
        elapsed_s=time.time() - t_start,
        eta_str="done",
        status="done",
    )
    state_writer.set_overall_state("VERIFYING")

    total = time.time() - t_start
    logger.info(f"=== SENDER DONE: {total:.1f}s total ===")
    return True
