"""
sender/pipeline.py — Main Sender Pipeline

Wires all sender modules into one callable.
Handles the end-to-end flow: file -> windows -> chunks -> RS -> fountain -> metadata -> serialization -> transmission.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import List, Optional

from data_diode.common.config import DEFAULT_CHUNK_SIZE
from data_diode.sender.m5_profile import get_profile, Profile
from data_diode.sender.m0_manifest import generate_manifest
from data_diode.sender.m1_windowing import get_file_window, compute_windows
from data_diode.sender.m2_chunker import chunk_window
from data_diode.sender.m3_merkle import build_merkle_tree, get_merkle_root
from data_diode.sender.m4_rs_encoder import encode_with_rs, RSConfig
from data_diode.sender.m6_fountain_encoder import encode_window_multipass
from data_diode.sender.m8_interleaver import interleave_packets
from data_diode.sender.m9_metadata import PacketEnvelope, sign_manifest, generate_ed25519_keypair
from data_diode.sender.m10_serializer import serialize_manifest, serialize_packet
from data_diode.sender.m11_transmitter import Transmitter, TransmitterConfig

logger = logging.getLogger(__name__)


import random

from data_diode.sender.m0_compress import compress_file

def run_sender(
    file_path: str,
    target_addr: tuple[str, int],
    criticality: str = "standard",
    sender_node_id: str = "sender-01",
    shared_secret: bytes = b"S" * 32,
    private_key: Optional[bytes] = None,
    loss_rate: float = 0.0,
) -> bool:
    """
    Run the complete sender pipeline with compression and optimized transmission.
    """
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    orig_size = os.path.getsize(file_path)
    logger.info(f"Starting transfer for {file_path} ({orig_size} bytes)")

    # 1. Compress file (CRITICAL OPTIMIZATION)
    temp_compressed_path = f"{file_path}.diode_tmp"
    comp_result = compress_file(file_path, temp_compressed_path)
    active_file_path = comp_result.compressed_path
    active_file_size = comp_result.compressed_size
    
    logger.info(f"Compression: {comp_result.algorithm} ({comp_result.original_size} -> {comp_result.compressed_size}, ratio={comp_result.compression_ratio:.2f}x)")

    # 2. Get profile and generate manifest
    profile = get_profile(active_file_size, criticality)
    manifest = generate_manifest(
        active_file_path,
        sender_node_id=sender_node_id,
        profile=profile,
        classification_level=criticality
    )
    
    # Update manifest with original file info for receiver decompression
    manifest.file_name = os.path.basename(file_path)
    manifest.compression_algorithm = comp_result.algorithm
    manifest.compressed_size = comp_result.compressed_size
    manifest.original_size = comp_result.original_size
    manifest.original_sha256 = comp_result.original_sha256

    # 3. Sign manifest if private key provided
    if private_key:
        from data_diode.sender.m9_metadata import import_private_key
        priv_key_obj = import_private_key(private_key) if isinstance(private_key, bytes) else private_key
        manifest_bytes_to_sign = serialize_manifest(manifest)
        manifest.ed25519_signature = sign_manifest(manifest_bytes_to_sign, priv_key_obj)

    # 4. Setup transmitter
    transmitter = Transmitter(TransmitterConfig(packets_per_second=2000))

    # 5. Phase 0: Send Manifest
    logger.info(f"Sending manifest ({profile.header_redundancy} copies)")
    serialized_manifest = serialize_manifest(manifest)
    manifest_batch = [serialized_manifest] * profile.header_redundancy
    transmitter.send_transfer(target_addr, manifest_batch)

    # 6. Phase 1: Send Data Windows
    windows = compute_windows(active_file_size, profile.window_size_bytes)
    
    for window in windows:
        window_id = window.window_id
        logger.info(f"Processing window {window_id}/{len(windows)} (size {window.num_bytes})")
        
        # Read window data
        window_data = get_file_window(active_file_path, window)
        
        # Chunk window
        chunk_result = chunk_window(window_data, manifest.chunk_size)
        
        # Reed-Solomon encoding
        rs_config = RSConfig(n=profile.rs_n, k=profile.rs_k)
        rs_chunks = encode_with_rs(chunk_result.chunks, rs_config)
        
        # Fountain encoding (multi-pass)
        logger.info(f"Step 6: Fountain Encoder — Generating LT packets (passes={profile.passes}, overhead {profile.overhead_ratio*100}%)")
        all_window_packets = encode_window_multipass(
            manifest.transfer_id,
            window_id,
            rs_chunks,
            profile.passes,
            profile.overhead_ratio
        )
        
        # Interleave across passes
        stride = profile.interleave_depth
        interleaved_payloads = []
        for i in range(stride):
            batch = all_window_packets[i::stride]
            for pkt in batch:
                # Simulate loss by just not serializing/sending
                if random.random() >= loss_rate:
                    interleaved_payloads.append(serialize_packet(pkt, shared_secret))

        logger.info(f"Sending {len(interleaved_payloads)} packets for window {window_id}")
        transmitter.send_transfer(target_addr, interleaved_payloads)

    # Cleanup temp file
    if active_file_path != file_path and os.path.exists(active_file_path):
        os.remove(active_file_path)

    logger.info("Transfer complete")
    transmitter.close()
    return True
