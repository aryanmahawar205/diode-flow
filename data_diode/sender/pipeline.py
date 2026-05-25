"""
sender/pipeline.py — Main Sender Pipeline (Streaming)
"""

from __future__ import annotations

import logging
import os
import uuid
import time
import gc
import math
from pathlib import Path
from typing import Optional

from sender.m5_profile import get_profile
from sender.m0_compress import compress_file
from sender.m0_manifest import generate_manifest
from sender.m1_windowing import get_file_window, compute_windows, get_window_size_for_file
from sender.m2_chunker import chunk_window
from sender.m3_merkle import compute_global_merkle_root_streaming
from sender.m4_rs_encoder import encode_with_rs, RSConfig, parse_rs_config
from fountain import get_encoder
from sender.m7_multipass import seed_for_pass
from sender.m8_interleaver import interleave_encoded_packets
from sender.m9_metadata import sign_manifest, import_private_key
from sender.m10_serializer import serialize_manifest, serialize_packet
from sender.m11_transmitter import Transmitter, TransmitterConfig

logger = logging.getLogger(__name__)


def run_sender(
    file_path: str,
    target_addr: tuple[str, int],
    criticality: str = "standard",
    sender_node_id: str = "sender-01",
    private_key: Optional[bytes] = None,
    chunk_size: int = 1200,   # Phase 2 default
    loss_rate: float = 0.0,
) -> bool:
    """
    Streaming sender pipeline.
    Memory footprint: ~200MB peak (one window at a time).
    Works for any file size.
    """
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    total_start = time.time()
    logger.info(f"Transfer start: {file_path} → {target_addr}")

    # Step 1: Compress (streaming)
    temp_path = f"{file_path}.lz4_tmp"
    try:
        compress_result = compress_file(file_path, temp_path)
        compressed_size = compress_result.compressed_size
        logger.info(f"Compressed {os.path.getsize(file_path) / 1024**2:.1f}MB → "
                    f"{compressed_size / 1024**2:.1f}MB "
                    f"({compress_result.compression_ratio:.1f}×)")

        # Step 2: Global Merkle Root (Streaming)
        logger.info("Computing global Merkle root...")
        global_merkle = compute_global_merkle_root_streaming(temp_path, chunk_size)

        # Step 3: Profile & Manifest
        profile = get_profile(compressed_size, criticality)
        manifest = generate_manifest(
            temp_path,
            sender_node_id=sender_node_id,
            profile=profile,
            classification_level=criticality,
            chunk_size=chunk_size,
            merkle_root=global_merkle,
            compress_result=compress_result
        )
        manifest.file_name = os.path.basename(file_path)

        # Step 4: Sign Manifest
        if private_key:
            priv_key_obj = import_private_key(private_key)
            manifest_bytes_to_sign = serialize_manifest(manifest)
            manifest.ed25519_signature = sign_manifest(manifest_bytes_to_sign, priv_key_obj)

        # Step 5: Transmitter
        transmitter = Transmitter(TransmitterConfig())

        # Step 6: Transmit Manifest (Redundant)
        logger.info(f"Transmitting manifest ({profile.header_redundancy}x)")
        manifest_bytes = serialize_manifest(manifest)
        for _ in range(profile.header_redundancy):
            transmitter._send_raw(target_addr, manifest_bytes)

        # Step 7: Window Loop (Streaming)
        window_size = get_window_size_for_file(compressed_size, profile)
        windows = compute_windows(compressed_size, window_size)
        encoder = get_encoder("lt")
        rs_config = parse_rs_config(profile.rs_config)

        import random # Move import outside loop
        for w in windows:
            t0 = time.time()

            # a. Read window
            window_data = get_file_window(Path(temp_path), w)

            # b. Chunk -> RS encode -> fountain encode -> interleave
            chunk_res = chunk_window(window_data, chunk_size)
            chunks_with_rs = encode_with_rs(chunk_res.chunks, rs_config)

            all_packets_by_pass = []
            for pass_id in range(profile.num_passes):
                seed = seed_for_pass(manifest.transfer_id, w.window_id, pass_id)

                # Calculate required packets with min floor
                K_prime_win = len(chunks_with_rs)
                overhead_packets = math.ceil(K_prime_win * profile.overhead_ratio)
                total_packets_needed = K_prime_win + overhead_packets

                # ENSURE MINIMUM PACKETS for tiny files (Fountain needs sample size)
                if total_packets_needed < 20:
                    # Bump overhead ratio for this specific tiny window
                    actual_overhead = (20 - K_prime_win) / K_prime_win
                else:
                    actual_overhead = profile.overhead_ratio

                packets = encoder.encode(chunks_with_rs, seed=seed, overhead_ratio=actual_overhead)
                for p in packets:
                    p.pass_id = pass_id
                    setattr(p, 'window_id', w.window_id) # Needed for serializer
                all_packets_by_pass.append(packets)

            transmitted = interleave_encoded_packets(all_packets_by_pass, profile.interleave_depth)

            # c. Transmit immediately
            for p in transmitted:
                if loss_rate > 0 and random.random() < loss_rate:
                    continue

                pkt_bytes = serialize_packet(p)
                transmitter._send_raw(target_addr, pkt_bytes)

            # d. Explicit memory free
            del window_data, chunk_res, chunks_with_rs, all_packets_by_pass, transmitted
            gc.collect()

            # e. Log progress
            elapsed = time.time() - t0
            pct = (w.window_id + 1) / len(windows) * 100
            logger.info(f"Window {w.window_id + 1}/{len(windows)} ({pct:.1f}%) sent in {elapsed:.1f}s")

        # Step 8: Footer x 3
        footer = f"TRANSFER_END:{manifest.transfer_id}".encode()
        for _ in range(3):
            transmitter._send_raw(target_addr, footer)

        total_elapsed = time.time() - total_start
        logger.info(f"Transfer complete: {total_elapsed:.1f}s total")
        transmitter.close()
        return True

    finally:
        # Step 9: Cleanup
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                logger.warning(f"Failed to remove temporary file {temp_path}: {e}")
