"""
receiver/pipeline.py — Streaming Receiver Pipeline
"""

from __future__ import annotations

import logging
import time
import os
import shutil
import gc
from pathlib import Path
from typing import Dict, Optional, Set

from common.models import TransferManifest, TransferProgress
from sender.m10_serializer import deserialize_manifest, deserialize_packet, MANIFEST_VERSION
from receiver.m12_receiver import Receiver
from receiver.m13_validator import PacketValidator, ManifestValidator
from receiver.m15_pooler import PacketPool
import fountain
from receiver.m16_fountain_decoder import FountainDecoderWrapper
from sender.m4_rs_encoder import RSConfig, decode_with_rs
from receiver.m18_merkle_verifier import MerkleVerifier
from receiver.m20_file_reassembler import FileReassembler
from receiver.m21_verifier import FileVerifier
from receiver.m24_decompress import decompress_file

logger = logging.getLogger(__name__)


def run_receiver(
    bind_addr: str = "0.0.0.0",
    bind_port: int = 20000,
    storage_dir: str = "demo_output/storage",
    quit_event: Optional[any] = None,
) -> None:
    """
    Run the streaming receiver pipeline.
    Memory footprint: ~200MB peak (one decode window at a time).
    Window temp files written to disk as each window completes.
    """
    logger.info(f"Starting streaming receiver on {bind_addr}:{bind_port}")
    
    receiver = Receiver(bind_addr, bind_port)
    packet_validator = PacketValidator()
    manifest_validator = ManifestValidator()
    packet_pool = PacketPool()
    fountain_decoder = FountainDecoderWrapper("lt")
    reassembler = FileReassembler()
    
    # State for current transfer
    manifest: Optional[TransferManifest] = None
    progress: Optional[TransferProgress] = None
    windows_done: Set[int] = set()
    window_files: Dict[int, Path] = {}
    window_roots: Dict[int, str] = {}
    window_retries: Dict[int, int] = {} # Track retry attempts
    
    # Critical Requirement 1: Create windows_tmp/
    windows_tmp_dir = Path(storage_dir) / "windows_tmp"
    if windows_tmp_dir.exists():
        shutil.rmtree(windows_tmp_dir)
    windows_tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        last_tick = time.time()
        while not (quit_event and quit_event.is_set()):
            # Critical Requirement 2: Receiving, validating, pooling
            raw = receiver.receive_nonblocking()
            if raw is None:
                # Periodic maintenance/timeouts
                if manifest and time.time() - last_tick > 2.0:
                    last_tick = time.time()
                    for wid in range(manifest.total_windows):
                        if wid not in windows_done:
                            K_prime = _compute_K_prime(manifest, wid)
                            retries = window_retries.get(wid, 0)
                            
                            # Trigger decode if threshold met OR after 20s idle (if we have ANY packets)
                            if packet_pool.is_ready_to_decode(manifest.transfer_id, wid, K_prime) or \
                               (retries < 10 and packet_pool.get_packet_count(manifest.transfer_id, wid) > 0):
                                
                                logger.info(f"Triggering decode attempt {retries+1} for window {wid}")
                                window_retries[wid] = retries + 1
                                if _process_window(wid, manifest, packet_pool, fountain_decoder, reassembler,
                                               windows_done, window_files, window_roots, windows_tmp_dir, progress):
                                    logger.info(f"Successfully recovered window {wid} on attempt {retries+1}")
                                elif retries >= 10:
                                    logger.error(f"GIVING UP on window {wid} after 10 failed attempts")
                time.sleep(0.001)
                continue
            
            # Handle Manifest
            if raw.payload[0] == MANIFEST_VERSION:
                try:
                    new_manifest = deserialize_manifest(raw.payload)
                    if manifest is None or new_manifest.transfer_id != manifest.transfer_id:
                        if not manifest_validator.validate_manifest_hard_limits(new_manifest).valid:
                            continue
                        logger.info(f"New Transfer: {new_manifest.file_name} ({new_manifest.file_size} bytes)")
                        manifest = new_manifest
                        progress = TransferProgress(
                            transfer_id=manifest.transfer_id,
                            file_name=manifest.file_name,
                            total_windows=manifest.total_windows
                        )
                        windows_done = set()
                        window_files = {}
                        window_roots = {}
                        # Clear any previous tmp files
                        for f in windows_tmp_dir.glob("*.bin"):
                            f.unlink()
                except Exception as e:
                    logger.debug(f"Failed to deserialize manifest: {e}")
                continue

            # Handle Footer (TRANSFER_END)
            if raw.payload.startswith(b"TRANSFER_END:"):
                tid = raw.payload.decode("utf-8").split(":")[-1]
                if manifest and tid == manifest.transfer_id:
                    if len(windows_done) < manifest.total_windows:
                        logger.warning(f"Footer received but only {len(windows_done)}/{manifest.total_windows} windows done")
                continue

            # Handle Packets
            if manifest is None:
                continue

            if raw.payload[0] != 0x52: # PACKET_VERSION
                continue

            packet = deserialize_packet(raw.payload)
            if packet is None:
                continue
            
            if not packet_validator.validate_packet(packet, manifest).valid:
                continue
            
            window_id = getattr(packet, 'window_id', 0)
            if window_id in windows_done:
                continue
                
            if packet_pool.add_packet(manifest.transfer_id, window_id, packet):
                if progress:
                    progress.total_packets += 1
                
                K_prime = _compute_K_prime(manifest, window_id)
                # Let maintenance loop handle the actual decode triggers to avoid 
                # blocking the receiver thread during high-volume bursts
                pass

            # Critical Requirement 5: When all windows complete
            if manifest and len(windows_done) == manifest.total_windows:
                _finalize_transfer(manifest, window_files, window_roots, reassembler, storage_dir)
                manifest = None 
                progress = None
                # Cleanup windows_tmp
                for f in windows_tmp_dir.glob("*.bin"):
                    try: f.unlink()
                    except: pass

    finally:
        receiver.close()
        if windows_tmp_dir.exists():
            shutil.rmtree(windows_tmp_dir)


def _compute_K_prime(manifest: TransferManifest, window_id: int) -> int:
    """Calculate expected packets (K') for a window."""
    # window_id is 0-indexed
    if window_id < manifest.total_windows - 1:
        win_size = manifest.window_size_bytes
    else:
        win_size = manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes
        
    K_win = (win_size + manifest.chunk_size - 1) // manifest.chunk_size
    num_blocks = (K_win + manifest.rs_k - 1) // manifest.rs_k
    return num_blocks * manifest.rs_n


def _process_window(window_id, manifest, packet_pool, fountain_decoder, reassembler, 
                    windows_done, window_files, window_roots, windows_tmp_dir, progress) -> bool:
    """
    Critical Requirement 3: Decode -> RS -> Merkle -> Write to Disk -> del -> clear pool
    Returns True on success.
    """
    K_prime = _compute_K_prime(manifest, window_id)
    pool = packet_pool.get_unified_pool(manifest.transfer_id, window_id)
    
    # 1. Fountain decode
    decode_result = fountain_decoder.decode_window(pool, K_prime, manifest.chunk_size)
    if not decode_result.success:
        return False
    
    # 2. RS Recovery
    rs_config = RSConfig(n=manifest.rs_n, k=manifest.rs_k)
    try:
        recovered_chunks = decode_with_rs(decode_result.chunks, rs_config)
        
        # Strip trailing chunks if the block padding added extra
        K_win = ((manifest.window_size_bytes if window_id < manifest.total_windows - 1 else 
                  (manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes))
                 + manifest.chunk_size - 1) // manifest.chunk_size
        recovered_chunks = recovered_chunks[:K_win]
        
        # 3. Merkle verify (Recompute root for this window)
        from sender.m3_merkle import build_merkle_tree, get_merkle_root
        tree_data = build_merkle_tree(recovered_chunks)
        window_roots[window_id] = get_merkle_root(tree_data)
        
        # 4. Assemble & Write to disk
        window_bytes = reassembler.assemble_window_data(recovered_chunks)
        temp_path = windows_tmp_dir / f"window_{window_id:06d}.bin"
        
        # Exact size this window should be (strip chunker padding)
        if window_id < manifest.total_windows - 1:
            this_window_size = manifest.window_size_bytes
        else:
            this_window_size = manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes

        with open(temp_path, 'wb') as f:
            f.write(window_bytes[:this_window_size])
        
        window_files[window_id] = temp_path
        windows_done.add(window_id)
        
        # 5. Critical Requirement: Free RAM and clear pool
        del pool, decode_result, recovered_chunks, window_bytes, tree_data
        packet_pool.clear_window(manifest.transfer_id, window_id)
        gc.collect()
        
        # 6. Critical Requirement 4: Logging
        if progress:
            progress.completed_windows = len(windows_done)
            eta = progress.eta_seconds
            eta_str = (f"{eta/60:.1f}min" if eta < 3600 else f"{eta/3600:.1f}hr"
                       if eta != float('inf') else "unknown")
            logger.info(f"Window {window_id + 1}/{manifest.total_windows} stored "
                       f"({progress.percent_complete:.1f}% complete) ETA: {eta_str}")
        
        return True
        
    except Exception as e:
        logger.debug(f"Intermediate recovery attempt for window {window_id} failed: {e}")
        return False


def _finalize_transfer(manifest, window_files, window_roots, reassembler, storage_dir):
    """
    Critical Requirement 5: Stream-assemble -> verify -> decompress -> quarantine
    """
    logger.info("All windows recovered. Finalizing transfer...")
    
    quarantine_dir = Path(storage_dir) / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    
    compressed_out = quarantine_dir / f"{manifest.transfer_id}.compressed"
    final_out = Path(storage_dir) / manifest.file_name
    
    # 1. Stream-assemble & Verify SHA-256
    success = reassembler.streaming_assemble(
        window_files,
        manifest.total_windows,
        compressed_out,
        manifest.file_sha256
    )
    
    if not success:
        logger.error("Reassembly or SHA-256 integrity check failed!")
        return

    # 2. Global Merkle Check
    all_roots = [window_roots[i] for i in range(manifest.total_windows)]
    if not FileVerifier.verify_merkle_root(all_roots, manifest.merkle_root):
        logger.error("Global Merkle root verification failed!")
        return

    # 3. Decompress (m24)
    logger.info("Decompressing and verifying original SHA-256...")
    success = decompress_file(
        str(compressed_out),
        str(final_out),
        manifest.compression_algorithm,
        manifest.original_sha256
    )
    
    if success:
        logger.info(f"Transfer SUCCESS: {manifest.file_name} saved to {storage_dir}")
        if compressed_out.exists():
            compressed_out.unlink()
    else:
        logger.error("Final decompression or original SHA-256 check failed!")
