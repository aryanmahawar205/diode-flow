"""
receiver/pipeline.py — Main Receiver Pipeline

Wires all receiver modules into one callable.
Handles the end-to-end flow: UDP receive -> validation -> pooling -> decoding -> RS -> reassembly -> verification -> storage.
"""

from __future__ import annotations

import logging
import time
import os
import multiprocessing
import queue
from typing import Dict, Optional, Set
from pathlib import Path

from data_diode.common.models import TransferManifest, TransferDecodeSession, WindowDecodeSession
from data_diode.sender.m10_serializer import deserialize_manifest, deserialize_packet, MANIFEST_VERSION
from data_diode.receiver.m12_receiver import Receiver, ReceiverConfig
from data_diode.receiver.m13_validator import PacketValidator, ManifestValidator
from data_diode.receiver.m15_pooler import PacketPool, PooledPacket
from data_diode.receiver.m16_fountain_decoder import FountainDecoderWrapper
from data_diode.sender.m4_rs_encoder import RSConfig
from data_diode.receiver.m17_rs_decoder import ReedSolomonDecoder
from data_diode.receiver.m18_merkle_verifier import verify_chunk_merkle
from data_diode.receiver.m19_window_reassembler import WindowReassembler
from data_diode.receiver.m20_file_reassembler import FileReassembler
from data_diode.receiver.m21_verifier import FileVerifier
from data_diode.receiver.m23_storage import StorageWriter

logger = logging.getLogger(__name__)


def _listener_process(bind_addr: str, bind_port: int, config: ReceiverConfig, packet_queue: multiprocessing.Queue, quit_event: multiprocessing.Event):
    """
    Dedicated process for high-speed UDP reception.
    Dumps raw payloads into the queue as fast as possible.
    """
    receiver = Receiver(bind_addr, bind_port, config)
    receiver._bind_socket()
    
    logger.info("Listener process started")
    try:
        while not quit_event.is_set():
            # Batch receive to reduce queue overhead
            batch = receiver.receive_batch(max_packets=100)
            if not batch:
                time.sleep(0.001) # Very short sleep
                continue
            
            for entry in batch:
                try:
                    packet_queue.put(entry.payload, block=False)
                except queue.Full:
                    # This should only happen if the decoder is catastrophically slow
                    pass
    finally:
        receiver.close()
        logger.info("Listener process exiting")


def run_receiver(
    bind_addr: str = "0.0.0.0",
    bind_port: int = 20000,
    storage_dir: str = "demo_output/storage",
    shared_secret: bytes = b"S" * 32,
    public_key: Optional[bytes] = None,
    quit_event: Optional[any] = None,
) -> None:
    """
    Run the complete receiver pipeline with multi-process isolation.
    """
    logger.info(f"Starting multi-process receiver on {bind_addr}:{bind_port}")
    
    # Internal quit event if none provided
    if quit_event is None:
        quit_event = multiprocessing.Event()
    
    # Queue for inter-process communication
    # 100k packets buffer in RAM
    packet_queue = multiprocessing.Queue(maxsize=100000)
    
    config = ReceiverConfig(buffer_slots=100000)
    
    # Start the listener process
    listener = multiprocessing.Process(
        target=_listener_process,
        args=(bind_addr, bind_port, config, packet_queue, quit_event),
        daemon=True
    )
    listener.start()
    
    packet_validator = PacketValidator()
    packet_pool = PacketPool()
    storage_writer = StorageWriter(storage_dir=storage_dir)
    
    active_transfers: Dict[str, TransferDecodeSession] = {}
    completed_transfers: Set[str] = set()

    try:
        last_periodic_check = time.time()
        
        while not quit_event.is_set():
            # 1. Drain the queue into pools
            dirty_windows = set()
            
            processed_in_batch = 0
            while processed_in_batch < 2000: # Process in chunks
                try:
                    payload = packet_queue.get_nowait()
                    processed_in_batch += 1
                    
                    if payload[0] == MANIFEST_VERSION:
                        manifest = deserialize_manifest(payload)
                        if manifest.transfer_id not in completed_transfers and manifest.transfer_id not in active_transfers:
                            logger.info(f"Received manifest: {manifest.file_name}")
                            active_transfers[manifest.transfer_id] = TransferDecodeSession(transfer_id=manifest.transfer_id, manifest=manifest)
                        continue

                    packet_proto = deserialize_packet(payload, shared_secret)
                    transfer_id = packet_proto.transfer_id
                    if transfer_id not in active_transfers: continue
                    
                    session = active_transfers[transfer_id]
                    
                    # Convert proto to EncodedPacket object for the pool
                    from data_diode.fountain.interface import EncodedPacket
                    pkt_obj = EncodedPacket(
                        packet_id=packet_proto.packet_id,
                        pass_id=packet_proto.pass_id,
                        seed=packet_proto.fountain_seed,
                        degree=packet_proto.fountain_degree,
                        chunk_ids=list(packet_proto.chunk_ids),
                        data=packet_proto.payload,
                        source_chunk_count=packet_proto.source_chunk_count,
                        transfer_id=transfer_id,
                        window_id=packet_proto.window_id
                    )

                    if packet_pool.add_packet(transfer_id, packet_proto.window_id, pkt_obj):
                        session.received_packets += 1
                        dirty_windows.add((transfer_id, packet_proto.window_id))
                except queue.Empty:
                    break
                except Exception:
                    continue

            # Periodic check for all active windows (every 2 seconds)
            # This ensures that even if no new packets arrived, we still try to decode
            # if we have enough packets but didn't hit a trigger_interval.
            if time.time() - last_periodic_check > 2.0:
                for tid, session in active_transfers.items():
                    for wid in range(session.manifest.total_windows):
                        dirty_windows.add((tid, wid))
                last_periodic_check = time.time()

            if processed_in_batch == 0 and not dirty_windows:
                time.sleep(0.01)
                continue

            # 2. Process dirty windows
            for transfer_id, window_id in dirty_windows:
                session = active_transfers.get(transfer_id)
                if not session: continue
                manifest = session.manifest
                
                if window_id not in session.windows:
                    session.windows[window_id] = WindowDecodeSession(transfer_id=transfer_id, window_id=window_id)
                
                window_session = session.windows[window_id]
                if window_session.is_complete: continue
                
                # Determine K_prime
                if window_id == manifest.total_windows - 1:
                    window_size = manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes
                else:
                    window_size = manifest.window_size_bytes
                
                W = (window_size + manifest.chunk_size - 1) // manifest.chunk_size
                num_blocks = (W + manifest.rs_k - 1) // manifest.rs_k
                K_prime = num_blocks * manifest.rs_n
                
                if not packet_pool.is_ready_to_decode(transfer_id, window_id, K_prime):
                    continue

                logger.info(f"Decoding window {window_id} ({packet_pool.get_packet_count(transfer_id, window_id)} packets, K'={K_prime})")
                
                decoder = FountainDecoderWrapper("lt")
                unified_pool = packet_pool.get_unified_pool(transfer_id, window_id)
                decode_result = decoder.decode_window(unified_pool, K_prime=K_prime, chunk_size=manifest.chunk_size)
                
                if decode_result.success:
                    rs_decoder = ReedSolomonDecoder(RSConfig(n=manifest.rs_n, k=manifest.rs_k))
                    try:
                        chunks = rs_decoder.decode(decode_result.chunks)
                        reassembler = WindowReassembler(window_id=window_id, chunk_size=manifest.chunk_size, expected_bytes=window_size)
                        for i in range(W):
                            reassembler.add_chunk(i, chunks[i])
                        
                        if reassembler.is_complete():
                            window_session.data = reassembler.get_window_bytes()
                            window_session.is_complete = True
                            logger.info(f"Window {window_id} complete")
                    except Exception as e:
                        logger.warning(f"RS failed for window {window_id}: {e}")
                
                # Check if all windows complete
                if len(session.windows) == manifest.total_windows and all(w.is_complete for w in session.windows.values()):
                    try:
                        final_data = b"".join(session.windows[i].data for i in range(manifest.total_windows))
                        
                        # Verify COMPRESSED file hash first
                        if not FileVerifier.verify_file(final_data, manifest.file_size, manifest.file_sha256)["valid"]:
                            logger.error(f"Integrity check failed for {manifest.file_name}")
                            continue

                        # DECOMPRESS (CRITICAL FINAL STEP)
                        from data_diode.receiver.m24_decompress import decompress_file
                        
                        # Temp paths for intermediate steps
                        temp_reconstructed = os.path.join(storage_dir, f"{manifest.transfer_id}.reconstructed")
                        temp_decompressed = os.path.join(storage_dir, f"{manifest.transfer_id}.decompressed")
                        
                        os.makedirs(storage_dir, exist_ok=True)
                        
                        with open(temp_reconstructed, 'wb') as f:
                            f.write(final_data)
                        
                        success = decompress_file(
                            temp_reconstructed,
                            temp_decompressed,
                            manifest.compression_algorithm,
                            manifest.original_sha256
                        )
                        
                        if success:
                            with open(temp_decompressed, 'rb') as f:
                                final_bytes = f.read()
                            
                            final_dest = storage_writer.store_file(final_bytes, manifest, session.received_packets)
                            logger.info(f"SUCCESS! Transfer complete: {os.path.basename(final_dest)}")
                            completed_transfers.add(transfer_id)
                        else:
                            logger.error(f"Decompression/Verification failed for {manifest.file_name}")
                        
                        # Cleanup all temps
                        for p in [temp_reconstructed, temp_decompressed]:
                            if os.path.exists(p): os.remove(p)
                        
                        del active_transfers[transfer_id]

                    except Exception as e:
                        logger.error(f"Reassembly/Decompression error: {e}")
                        completed_transfers.add(transfer_id)
                        del active_transfers[transfer_id]

    finally:
        quit_event.set()
        listener.join(timeout=1)
        if listener.is_alive():
            listener.terminate()
