"""
receiver/pipeline.py — Streaming Receiver Pipeline
"""

from __future__ import annotations

import logging
import time
import os
import shutil
import gc
import threading
from collections import deque
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
    """
    logger.info(f"Starting streaming receiver on {bind_addr}:{bind_port}")
    
    receiver = Receiver(bind_addr, bind_port)
    packet_validator = PacketValidator()
    manifest_validator = ManifestValidator()
    packet_pool = PacketPool()
    fountain_decoder = FountainDecoderWrapper("lt")
    reassembler = FileReassembler()
    
    manifest: Optional[TransferManifest] = None
    progress: Optional[TransferProgress] = None
    windows_done: Set[int] = set()
    window_files: Dict[int, Path] = {}
    window_roots: Dict[int, str] = {}
    window_retries: Dict[int, int] = {} 
    
    windows_tmp_dir = Path(storage_dir) / "windows_tmp"
    if windows_tmp_dir.exists():
        try: shutil.rmtree(windows_tmp_dir)
        except: pass
    windows_tmp_dir.mkdir(parents=True, exist_ok=True)

    packet_queue = deque()
    
    def background_rx():
        while not (quit_event and quit_event.is_set()):
            raw_pkt = receiver.receive_nonblocking()
            if raw_pkt:
                packet_queue.append(raw_pkt)
            else:
                time.sleep(0.0001)
                
    rx_thread = threading.Thread(target=background_rx, daemon=True)
    rx_thread.start()

    try:
        last_tick = time.time()
        packet_count_since_tick = 0
        while not (quit_event and quit_event.is_set()):
            if not packet_queue:
                if manifest and time.time() - last_tick > 2.0:
                    last_tick = time.time()
                    _run_maintenance(manifest, windows_done, window_retries, packet_pool,
                                    fountain_decoder, reassembler, windows_tmp_dir, 
                                    window_files, window_roots, progress)
                time.sleep(0.001)
                continue
            
            raw = packet_queue.popleft()
            packet_count_since_tick += 1
            
            if packet_count_since_tick > 100:
                packet_count_since_tick = 0
                if manifest and time.time() - last_tick > 2.0:
                    last_tick = time.time()
                    _run_maintenance(manifest, windows_done, window_retries, packet_pool,
                                    fountain_decoder, reassembler, windows_tmp_dir, 
                                    window_files, window_roots, progress)

            # Handle Manifest
            if raw.payload[0] == MANIFEST_VERSION:
                try:
                    new_manifest = deserialize_manifest(raw.payload)
                    if manifest is None or new_manifest.transfer_id != manifest.transfer_id:
                        if not manifest_validator.validate_manifest_hard_limits(new_manifest).valid:
                            continue
                        logger.info(f"New Transfer: {new_manifest.file_name} ({new_manifest.file_size} bytes)")
                        manifest = new_manifest
                        progress = TransferProgress(manifest.transfer_id, manifest.file_name, manifest.total_windows)
                        windows_done = set()
                        window_files, window_roots, window_retries = {}, {}, {}
                        for f in windows_tmp_dir.glob("*.bin"):
                            try: f.unlink()
                            except: pass
                except Exception as e:
                    logger.debug(f"Manifest error: {e}")
                continue

            if raw.payload.startswith(b"TRANSFER_END:"):
                tid = raw.payload.decode("utf-8").split(":")[-1]
                if manifest and tid == manifest.transfer_id:
                    _run_maintenance(manifest, windows_done, window_retries, packet_pool,
                                    fountain_decoder, reassembler, windows_tmp_dir, 
                                    window_files, window_roots, progress, force=True)
                continue

            if manifest is None: continue

            packet = deserialize_packet(raw.payload)
            if packet is None: continue
            
            if not packet_validator.validate_packet(packet, manifest).valid: continue
            
            window_id = getattr(packet, 'window_id', 0)
            if window_id in windows_done: continue
                
            if packet_pool.add_packet(manifest.transfer_id, window_id, packet):
                if progress: progress.total_packets += 1
                K_prime = _compute_K_prime(manifest, window_id)
                if packet_pool.is_ready_to_decode(manifest.transfer_id, window_id, K_prime):
                    _process_window(window_id, manifest, packet_pool, fountain_decoder, reassembler,
                                   windows_done, window_files, window_roots, windows_tmp_dir, progress)

            if manifest and len(windows_done) == manifest.total_windows:
                _finalize_transfer(manifest, window_files, window_roots, reassembler, storage_dir)
                manifest, progress = None, None

    finally:
        receiver.close()
        if windows_tmp_dir.exists():
            try: shutil.rmtree(windows_tmp_dir)
            except: pass

def _run_maintenance(manifest, windows_done, window_retries, packet_pool,
                    fountain_decoder, reassembler, windows_tmp_dir, 
                    window_files, window_roots, progress, force=False):
    for wid in range(manifest.total_windows):
        if wid not in windows_done:
            K_prime = _compute_K_prime(manifest, wid)
            retries = window_retries.get(wid, 0)
            count = packet_pool.get_packet_count(manifest.transfer_id, wid)
            
            ready = packet_pool.is_ready_to_decode(manifest.transfer_id, wid, K_prime)
            if force or ready or (retries < 10 and count > 0):
                if not ready and not force and retries < 5: continue # Wait a bit longer for natural ready
                
                logger.info(f"Maintenance: decode attempt {retries+1} for window {wid} ({count} packets)")
                window_retries[wid] = retries + 1
                if _process_window(wid, manifest, packet_pool, fountain_decoder, reassembler,
                               windows_done, window_files, window_roots, windows_tmp_dir, progress):
                    logger.info(f"Recovered window {wid} via maintenance")

def _compute_K_prime(manifest: TransferManifest, window_id: int) -> int:
    if window_id < manifest.total_windows - 1:
        win_size = manifest.window_size_bytes
    else:
        win_size = manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes
    K_win = (win_size + manifest.chunk_size - 1) // manifest.chunk_size
    num_blocks = (K_win + manifest.rs_k - 1) // manifest.rs_k
    return num_blocks * manifest.rs_n

def _process_window(window_id, manifest, packet_pool, fountain_decoder, reassembler, 
                    windows_done, window_files, window_roots, windows_tmp_dir, progress) -> bool:
    K_prime = _compute_K_prime(manifest, window_id)
    pool = packet_pool.get_unified_pool(manifest.transfer_id, window_id)
    decode_result = fountain_decoder.decode_window(pool, K_prime, manifest.chunk_size)
    if not decode_result.success: return False
    
    rs_config = RSConfig(n=manifest.rs_n, k=manifest.rs_k)
    try:
        recovered_chunks = decode_with_rs(decode_result.chunks, rs_config)
        win_size = manifest.window_size_bytes if window_id < manifest.total_windows - 1 else \
                   (manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes)
        K_win = (win_size + manifest.chunk_size - 1) // manifest.chunk_size
        recovered_chunks = recovered_chunks[:K_win]
        
        from sender.m3_merkle import compute_merkle_root_from_chunks
        window_roots[window_id] = compute_merkle_root_from_chunks(recovered_chunks)
        
        window_bytes = reassembler.assemble_window_data(recovered_chunks)
        temp_path = windows_tmp_dir / f"window_{window_id:06d}.bin"
        with open(temp_path, 'wb') as f:
            f.write(window_bytes[:win_size])
        
        window_files[window_id] = temp_path
        windows_done.add(window_id)
        packet_pool.clear_window(manifest.transfer_id, window_id)
        if progress:
            progress.completed_windows = len(windows_done)
            progress.log()
        return True
    except Exception as e:
        logger.debug(f"Recovery failed for window {window_id}: {e}")
        return False

def _finalize_transfer(manifest, window_files, window_roots, reassembler, storage_dir):
    logger.info("Finalizing transfer...")
    quarantine_dir = Path(storage_dir) / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    compressed_out = quarantine_dir / f"{manifest.transfer_id}.compressed"
    final_out = Path(storage_dir) / manifest.file_name
    
    if reassembler.streaming_assemble(window_files, manifest.total_windows, compressed_out, manifest.file_sha256):
        all_roots = [window_roots[i] for i in range(manifest.total_windows)]
        if FileVerifier.verify_merkle_root(all_roots, manifest.merkle_root):
            if decompress_file(str(compressed_out), str(final_out), manifest.compression_algorithm, manifest.original_sha256):
                logger.info(f"Transfer SUCCESS: {manifest.file_name}")
                if compressed_out.exists():
                    try: compressed_out.unlink()
                    except: pass
                return
    logger.error("Finalization failed!")
