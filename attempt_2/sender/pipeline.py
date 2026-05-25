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
from common.config import DEFAULT_CHUNK_SIZE, QUARANTINE_DIR
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

    # Step 1: Profile
    file_size = os.path.getsize(file_path)
    profile   = select_profile(file_size, criticality)
    win_size  = select_window_size(file_size)
    rs_config = RSConfig(n=profile.rs_n, k=profile.rs_k)

    # Step 2: Compress (streaming — never loads whole file)
    with tempfile.NamedTemporaryFile(suffix=".lz4", delete=False) as tmp:
        compressed_path = tmp.name

    compress_result = compress_file(file_path, compressed_path)
    compressed_size = compress_result.compressed_size

    # Step 3: Windows
    windows    = compute_windows(compressed_size, win_size)
    n_windows  = len(windows)

    # Step 4: Manifest
    manifest       = generate_manifest(compressed_path, compress_result,
                                       n_windows, win_size, profile, criticality)
    manifest_bytes = serialize_manifest(manifest)

    # Step 5: Transmitter
    tx = Transmitter(packets_per_second)

    # Step 6: Send manifest
    for _ in range(profile.header_redundancy):
        tx.send_raw(remote_addr, manifest_bytes)
    logger.info(f"Manifest sent ×{profile.header_redundancy}")

    # Step 7: Process and send windows ONE AT A TIME
    progress = TransferProgress(manifest.transfer_id,
                                os.path.basename(file_path), n_windows)

    for window in windows:
        t_win = time.time()

        # Read ONE window
        window_data = read_window(Path(compressed_path), window)

        # Chunk with global ID offset
        chunk_id_offset = window.start_byte // DEFAULT_CHUNK_SIZE
        chunk_result    = chunk_window(window_data, DEFAULT_CHUNK_SIZE,
                                       chunk_id_offset)

        # RS encode
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

        # FREE MEMORY — critical for GB scale
        del window_data, chunk_result, chunks_with_parity
        del encoded_pkts, passes, passes_list, interleaved

        # Progress
        progress.completed_windows += 1
        elapsed = time.time() - t_win
        logger.info(f"Window {window.window_id+1}/{n_windows} "
                    f"({progress.pct:.1f}%) sent in {elapsed:.1f}s "
                    f"| ETA: {progress.eta_str}")

    # Footer
    footer = b"DIODE_TRANSFER_END"
    for _ in range(3):
        tx.send_raw(remote_addr, footer)

    tx.close()
    os.remove(compressed_path)

    total = time.time() - t_start
    logger.info(f"=== SENDER DONE: {total:.1f}s total ===")
    return True
