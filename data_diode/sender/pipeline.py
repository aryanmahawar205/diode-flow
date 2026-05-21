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

from data_diode.common.config import get_profile, DEFAULT_CHUNK_SIZE
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
    Run the complete sender pipeline for a file.

    Parameters:
        file_path: Path to file to transfer.
        target_addr: (ip, port) of receiver.
        criticality: "standard" | "critical" | "classified".
        sender_node_id: Identifier for this sender.
        shared_secret: 32-byte secret for BLAKE3-MAC.
        private_key: Ed25519 private key (bytes or object) for manifest signing (optional).
        loss_rate: Probability (0.0 - 1.0) of dropping each packet to simulate network loss.

    Returns:
        True if transmission completed successfully.
    """
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    file_size = os.path.getsize(file_path)
    logger.info(f"Starting transfer for {file_path} ({file_size} bytes)")

    # 1. Get profile and generate initial manifest (without signature)
    profile = get_profile(file_size, criticality)
    manifest = generate_manifest(
        file_path,
        sender_node_id=sender_node_id,
        profile=profile,
        classification_level=criticality
    )

    # 2. Sign manifest if private key provided
    if private_key:
        from data_diode.sender.m9_metadata import import_private_key
        if isinstance(private_key, bytes):
            priv_key_obj = import_private_key(private_key)
        else:
            priv_key_obj = private_key
        
        # Serialize once to sign
        manifest_bytes_to_sign = serialize_manifest(manifest)
        manifest.ed25519_signature = sign_manifest(manifest_bytes_to_sign, priv_key_obj)

    # 3. Setup transmitter
    tx_config = TransmitterConfig(
        packets_per_second=2000  # Default rate limit
    )
    transmitter = Transmitter(tx_config)

    # Metrics
    total_packets_attempted = 0
    total_packets_dropped = 0

    # 4. Phase 0: Send Manifest
    logger.info(f"Sending manifest ({profile.header_redundancy} copies)")
    serialized_manifest = serialize_manifest(manifest)
    for _ in range(profile.header_redundancy):
        total_packets_attempted += 1
        if random.random() >= loss_rate:
            transmitter.send_packet(target_addr, serialized_manifest)
        else:
            total_packets_dropped += 1
        time.sleep(0.01)

    # 5. Phase 1: Send Data Windows
    windows = compute_windows(file_size, profile.window_size_bytes)
    
    for window in windows:
        window_id = window.window_id
        logger.info(f"Processing window {window_id}/{len(windows)} (offset {window.start_byte}, size {window.num_bytes})")
        
        # Read window data
        window_data = get_file_window(file_path, window)
        
        # Chunk window
        logger.info(f"Step 2: Chunker — Dividing window into {manifest.chunk_size} byte chunks")
        chunk_result = chunk_window(window_data, manifest.chunk_size)
        
        # Reed-Solomon encoding
        logger.info(f"Step 4: RS Encoder — Adding {profile.rs_n - profile.rs_k} parity chunks")
        rs_config = RSConfig(n=profile.rs_n, k=profile.rs_k)
        rs_chunks = encode_with_rs(chunk_result.chunks, rs_config)
        
        # Fountain encoding (multi-pass)
        logger.info(f"Step 6: Fountain Encoder — Generating LT packets (overhead {profile.overhead_ratio*100}%)")
        encoded_packets = encode_window_multipass(
            manifest.transfer_id,
            window_id,
            rs_chunks,
            profile.num_passes,
            profile.overhead_ratio
        )
        
        # Interleave packets
        stride = profile.interleave_depth
        interleaved_packets = []
        for i in range(stride):
            interleaved_packets.extend(encoded_packets[i::stride])

        logger.info(f"Sending {len(interleaved_packets)} packets for window {window_id}")
        
        for pkt in interleaved_packets:
            total_packets_attempted += 1
            # Simulate loss
            if random.random() < loss_rate:
                total_packets_dropped += 1
                continue

            # Attach security envelope and serialize
            try:
                packet_bytes = serialize_packet(pkt, shared_secret)
                
                # Send with rate control and pacing
                while transmitter.send_packet(target_addr, packet_bytes) == -1:
                    time.sleep(0.0001)
                
                # Tiny delay to prevent UDP buffer overflow in loopback
                time.sleep(0.0005) 
            except Exception as e:
                logger.error(f"Error sending packet: {e}")
                continue

    if total_packets_attempted > 0:
        actual_loss_percent = (total_packets_dropped / total_packets_attempted) * 100
        logger.info(f"Transmission METRICS: Total={total_packets_attempted}, Dropped={total_packets_dropped}, Loss={actual_loss_percent:.2f}%")

    logger.info("Transfer complete")
    transmitter.close()
    return True
