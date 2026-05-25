"""
receiver/pipeline.py — Streaming Receiver Pipeline
"""

from __future__ import annotations

import logging
import time
import os
import shutil
from pathlib import Path
from typing import Dict, Optional, Set

from data_diode.common.models import TransferManifest
from data_diode.sender.m10_serializer import deserialize_manifest, deserialize_packet, MANIFEST_VERSION
from data_diode.receiver.m12_receiver import Receiver
from data_diode.receiver.m13_validator import PacketValidator, ManifestValidator
from data_diode.receiver.m15_pooler import PacketPool
from data_diode.receiver.m16_fountain_decoder import FountainDecoderWrapper
from data_diode.receiver.m17_rs_decoder import ReedSolomonDecoder
from data_diode.receiver.m18_merkle_verifier import MerkleVerifier
from data_diode.receiver.m21_verifier import FileVerifier
from data_diode.receiver.m24_decompress import decompress_file

logger = logging.getLogger(__name__)


def run_receiver(
    bind_addr: str = "0.0.0.0",
    bind_port: int = 20000,
    storage_dir: str = "demo_output/storage",
    quit_event: Optional[any] = None,
) -> None:
    """
    Run the streaming receiver pipeline.
    Processes windows one-by-one and flushes them to disk to save RAM.
    """
    logger.info(f"Starting streaming receiver on {bind_addr}:{bind_port}")
    
    receiver = Receiver(bind_addr, bind_port)
    packet_validator = PacketValidator()
    manifest_validator = ManifestValidator()
    packet_pool = PacketPool()
    fountain_decoder = FountainDecoderWrapper("lt")
    merkle_verifier = MerkleVerifier()
    
    # State for current transfer (Phase 2 handles one transfer at a time)
    manifest: Optional[TransferManifest] = None
    windows_done: Set[int] = set()
    window_roots: Dict[int, str] = {}
    temp_dir = Path(storage_dir) / "tmp_reassembly"
    
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        last_tick = time.time()
        pkt_count = 0
        added_count = 0
        while not (quit_event and quit_event.is_set()):
            raw = receiver.receive_nonblocking()
            if raw is None:
                # Periodic maintenance
                now = time.time()
                if now - last_tick > 1.0:
                    logger.debug(f"Receiver idle, got {pkt_count} raw, {added_count} added")
                    last_tick = now
                if manifest:
                    packet_pool.cleanup_old_transfers()
                    # Check for timed-out windows
                    for wid in range(manifest.total_windows):
                        if wid not in windows_done:
                            W = _get_chunks_in_window(manifest, wid)
                            num_blocks = (W + manifest.rs_k - 1) // manifest.rs_k
                            K_prime = num_blocks * manifest.rs_n
                            if packet_pool.is_ready_to_decode(manifest.transfer_id, wid, K_prime):
                                logger.info(f"Triggering timeout decode for window {wid}")
                                _process_window(wid, manifest, packet_pool, fountain_decoder, 
                                               windows_done, window_roots, temp_dir)
                time.sleep(0.001)
                continue
            
            # 1. Handle Manifest
            if raw.payload[0] == MANIFEST_VERSION:
                try:
                    new_manifest = deserialize_manifest(raw.payload)
                    if manifest is None or new_manifest.transfer_id != manifest.transfer_id:
                        # Validate new manifest
                        if not manifest_validator.validate_manifest_hard_limits(new_manifest).valid:
                            continue
                        logger.info(f"New Transfer: {new_manifest.file_name} ({new_manifest.file_size} bytes)")
                        manifest = new_manifest
                        windows_done = set()
                        window_roots = {}
                        added_count = 0
                except Exception as e:
                    logger.debug(f"Failed to deserialize manifest: {e}")
                continue

            # 2. Handle Packets
            if manifest is None:
                continue

            pkt_count += 1
            packet = deserialize_packet(raw.payload)
            if packet is None:
                continue
            
            # Validate packet
            if not packet_validator.validate_packet(packet, manifest).valid:
                continue
            
            window_id = getattr(packet, 'window_id', 0)
            if window_id in windows_done:
                continue
                
            # Add to pool
            if packet_pool.add_packet(manifest.transfer_id, window_id, packet):
                added_count += 1
                # Readiness trigger
                W = _get_chunks_in_window(manifest, window_id)
                num_blocks = (W + manifest.rs_k - 1) // manifest.rs_k
                K_prime = num_blocks * manifest.rs_n
                
                if packet_pool.is_ready_to_decode(manifest.transfer_id, window_id, K_prime):
                    logger.info(f"Triggering decode for window {window_id} ({packet_pool.get_packet_count(manifest.transfer_id, window_id)} pkts)")
                    _process_window(window_id, manifest, packet_pool, fountain_decoder, 
                                   windows_done, window_roots, temp_dir)

            # 3. Check for Completion
            if manifest and len(windows_done) == manifest.total_windows:
                _finalize_transfer(manifest, windows_done, window_roots, temp_dir, storage_dir)
                manifest = None # Reset for next transfer

    finally:
        receiver.close()
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def _get_chunks_in_window(manifest: TransferManifest, window_id: int) -> int:
    """Calculate number of original chunks in a given window."""
    if window_id < manifest.total_windows - 1:
        window_size = manifest.window_size_bytes
    else:
        window_size = manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes
    return (window_size + manifest.chunk_size - 1) // manifest.chunk_size


def _process_window(window_id, manifest, packet_pool, fountain_decoder, windows_done, window_roots, temp_dir):
    """Decode, verify, and flush one window to disk."""
    W = _get_chunks_in_window(manifest, window_id)
    num_blocks = (W + manifest.rs_k - 1) // manifest.rs_k
    K_prime = num_blocks * manifest.rs_n
    
    pool = packet_pool.get_unified_pool(manifest.transfer_id, window_id)
    decode_result = fountain_decoder.decode_window(pool, K_prime, manifest.chunk_size)
    
    # RS Recovery
    from data_diode.sender.m4_rs_encoder import RSConfig
    from data_diode.receiver.m17_rs_decoder import decode_with_rs
    rs_config = RSConfig(n=manifest.rs_n, k=manifest.rs_k)
    
    try:
        recovered_chunks = decode_with_rs(decode_result.chunks, rs_config)
        # recovered_chunks contains K_original chunks
        
        # Strip trailing chunks if the block padding added extra
        recovered_chunks = recovered_chunks[:W]
        
        # Flush to disk
        window_file = temp_dir / f"window_{window_id}.part"
        with open(window_file, 'wb') as f:
            for i, chunk in enumerate(recovered_chunks):
                # Handle last window last chunk padding
                if window_id == manifest.total_windows - 1 and i == len(recovered_chunks) - 1:
                    last_chunk_size = manifest.file_size % manifest.chunk_size or manifest.chunk_size
                    f.write(chunk[:last_chunk_size])
                else:
                    f.write(chunk)
        
        # Compute window root for global Merkle check
        from data_diode.sender.m3_merkle import build_merkle_tree, get_merkle_root
        tree_data = build_merkle_tree(recovered_chunks)
        window_roots[window_id] = get_merkle_root(tree_data)
        
        windows_done.add(window_id)
        packet_pool.clear_window(manifest.transfer_id, window_id)
        logger.info(f"Window {window_id} recovered and flushed")
        
    except Exception as e:
        logger.error(f"Failed to recover window {window_id}: {e}")


def _finalize_transfer(manifest, windows_done, window_roots, temp_dir, storage_dir):
    """Assemble windows, verify, and decompress."""
    logger.info("All windows received. Finalizing...")
    
    reconstructed_path = Path(storage_dir) / f"{manifest.transfer_id}.tmp"
    final_path = Path(storage_dir) / manifest.file_name
    
    # 1. Reassemble windows
    with open(reconstructed_path, 'wb') as f_out:
        for i in range(manifest.total_windows):
            window_file = temp_dir / f"window_{i}.part"
            with open(window_file, 'rb') as f_in:
                shutil.copyfileobj(f_in, f_out)
    
    # 2. Global Merkle Check
    all_roots = [window_roots[i] for i in range(manifest.total_windows)]
    if not FileVerifier.verify_merkle_root(all_roots, manifest.merkle_root):
        logger.error("Global Merkle root mismatch!")
        return

    # 3. SHA-256 Check (on compressed file)
    if not FileVerifier.verify_sha256_streaming(str(reconstructed_path), manifest.file_sha256):
        logger.error("Compressed SHA-256 mismatch!")
        return

    # 4. Decompress
    logger.info("Decompressing...")
    success = decompress_file(
        str(reconstructed_path),
        str(final_path),
        manifest.compression_algorithm,
        manifest.original_sha256
    )
    
    if success:
        logger.info(f"Transfer SUCCESS: {manifest.file_name}")
    else:
        logger.error("Decompression or original SHA-256 failed!")
