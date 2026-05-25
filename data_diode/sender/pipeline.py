"""
sender/pipeline.py — Main Sender Pipeline (Streaming)
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from data_diode.sender.m5_profile import get_profile
from data_diode.sender.m0_compress import compress_file
from data_diode.sender.m0_manifest import generate_manifest
from data_diode.sender.m1_windowing import get_file_window, compute_windows, get_window_size_for_file
from data_diode.sender.m2_chunker import chunk_window
from data_diode.sender.m3_merkle import compute_global_merkle_root_streaming
from data_diode.sender.m4_rs_encoder import encode_with_rs, RSConfig
from data_diode.fountain.interface import get_encoder
from data_diode.sender.m7_multipass import seed_for_pass
from data_diode.sender.m8_interleaver import interleave_encoded_packets
from data_diode.sender.m9_metadata import sign_manifest, import_private_key
from data_diode.sender.m10_serializer import serialize_manifest, serialize_packet
from data_diode.sender.m11_transmitter import Transmitter, TransmitterConfig

logger = logging.getLogger(__name__)


def run_sender(
    file_path: str,
    target_addr: tuple[str, int],
    criticality: str = "standard",
    sender_node_id: str = "sender-01",
    private_key: Optional[bytes] = None,
    chunk_size: int = 384,
    loss_rate: float = 0.0,
) -> bool:
    """
    Run the streaming sender pipeline.
    Safe for GB-scale files.
    """
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    # 1. Compress
    temp_path = f"{file_path}.diode_tmp"
    try:
        compress_result = compress_file(file_path, temp_path)
        compressed_size = compress_result.compressed_size

        # 2. Global Merkle Root (Streaming)
        logger.info("Computing global Merkle root...")
        global_merkle = compute_global_merkle_root_streaming(temp_path, chunk_size)

        # 3. Profile & Manifest
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
        
        # 4. Sign Manifest
        if private_key:
            priv_key_obj = import_private_key(private_key)
            manifest_bytes = serialize_manifest(manifest)
            manifest.ed25519_signature = sign_manifest(manifest_bytes, priv_key_obj)

        # 5. Transmitter
        transmitter = Transmitter(TransmitterConfig())

        # 6. Transmit Manifest (Redundant)
        logger.info(f"Transmitting manifest ({profile.header_redundancy}x)")
        manifest_bytes = serialize_manifest(manifest)
        for _ in range(profile.header_redundancy):
            transmitter._send_raw(target_addr, manifest_bytes)

        # 7. Window Loop (Streaming)
        active_window_size = get_window_size_for_file(compressed_size, profile)
        windows = compute_windows(compressed_size, active_window_size)
        encoder = get_encoder("lt")
        rs_config = RSConfig(n=profile.rs_n, k=profile.rs_k)

        for w in windows:
            logger.info(f"Processing window {w.window_id}/{len(windows)}")
            window_data = get_file_window(temp_path, w)
            chunk_res = chunk_window(window_data, chunk_size)
            
            # RS encoding
            chunks_with_rs = encode_with_rs(chunk_res.chunks, rs_config)
            
            # Fountain encode — all passes
            all_packets = []
            for pass_id in range(profile.num_passes):
                seed = seed_for_pass(manifest.transfer_id, w.window_id, pass_id)
                packets = encoder.encode(chunks_with_rs, seed=seed, overhead_ratio=profile.overhead_ratio)
                for p in packets:
                    p.pass_id = pass_id
                    # Note: window_id is needed for deserializer but not in EncodedPacket dataclass
                    # We'll rely on the serializer to handle it or the receiver to know context
                    # Wait, my serializer doesn't include window_id!
                    # I should update the serializer to include window_id.
                all_packets.extend(packets)

            # Interleave
            transmitted = interleave_encoded_packets(all_packets, profile.interleave_depth)

            # Serialize & Send
            import random
            for p in transmitted:
                if loss_rate > 0 and random.random() < loss_rate:
                    continue
                # We need to tell the serializer which window this is
                setattr(p, 'window_id', w.window_id)
                pkt_bytes = serialize_packet(p)
                transmitter._send_raw(target_addr, pkt_bytes)

        logger.info("Transfer complete")
        transmitter.close()
        return True

    finally:
        # 8. Cleanup
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                logger.warning(f"Failed to remove temporary file {temp_path}: {e}")
