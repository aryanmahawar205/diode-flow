"""
receiver/pipeline.py — Main Receiver Pipeline

Wires all receiver modules into one callable.
Handles the end-to-end flow: UDP receive -> validation -> pooling -> decoding -> RS -> reassembly -> verification -> storage.
"""

from __future__ import annotations

import logging
import time
import os
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


def run_receiver(
    bind_addr: str = "0.0.0.0",
    bind_port: int = 20000,
    storage_dir: str = "demo_output/storage",
    shared_secret: bytes = b"S" * 32,
    public_key: Optional[bytes] = None,
    quit_event: Optional[any] = None,
) -> None:
    """
    Run the complete receiver pipeline.
    """
    logger.info(f"Starting receiver on {bind_addr}:{bind_port}")
    
    config = ReceiverConfig(buffer_slots=100000)
    receiver = Receiver(bind_addr, bind_port, config)
    receiver._bind_socket()
    
    packet_validator = PacketValidator()
    manifest_validator = ManifestValidator()
    packet_pool = PacketPool()
    storage_writer = StorageWriter(storage_dir=storage_dir)
    
    active_transfers: Dict[str, TransferDecodeSession] = {}
    completed_transfers: Set[str] = set()

    try:
        while quit_event is None or not quit_event.is_set():
            # 1. Drain all available packets into pools as fast as possible
            batch = receiver.receive_batch(max_packets=1000)
            if not batch:
                time.sleep(0.01)
                continue
            
            # Keep track of which windows received new packets in this batch
            dirty_windows = set() # (transfer_id, window_id)

            for entry in batch:
                try:
                    if entry.payload[0] == MANIFEST_VERSION:
                        manifest = deserialize_manifest(entry.payload)
                        if manifest.transfer_id not in completed_transfers and manifest.transfer_id not in active_transfers:
                            logger.info(f"Received manifest: {manifest.file_name}")
                            active_transfers[manifest.transfer_id] = TransferDecodeSession(transfer_id=manifest.transfer_id, manifest=manifest)
                        continue

                    packet_proto = deserialize_packet(entry.payload, shared_secret)
                    transfer_id = packet_proto.transfer_id
                    if transfer_id not in active_transfers: continue
                    
                    session = active_transfers[transfer_id]
                    if not packet_validator.validate_window_id(packet_proto.window_id, session.manifest.total_windows).valid: continue
                    
                    pooled = PooledPacket(
                        payload=packet_proto.payload, pass_id=packet_proto.pass_id,
                        packet_id=packet_proto.packet_id, degree=packet_proto.fountain_degree,
                        fountain_seed=packet_proto.fountain_seed
                    )
                    packet_pool.add_packet(transfer_id, packet_proto.window_id, pooled)
                    session.received_packets += 1
                    dirty_windows.add((transfer_id, packet_proto.window_id))
                except Exception:
                    continue

            # Heartbeat logging every 1000 packets
            if receiver.packet_count % 1000 == 0:
                stats = []
                for tid, sess in active_transfers.items():
                    for wid in range(sess.manifest.total_windows):
                        pkts = len(packet_pool.get_packets(tid, wid))
                        if pkts > 0: stats.append(f"W{wid}:{pkts}")
                if stats: logger.info(f"Receiver Status: {receiver.packet_count} total pkts. Pools: {', '.join(stats)}")

            # 2. After draining, check dirty windows for decode readiness
            for transfer_id, window_id in dirty_windows:
                session = active_transfers.get(transfer_id)
                if not session: continue
                manifest = session.manifest
                
                # Setup window session if needed
                if window_id not in session.windows:
                    session.windows[window_id] = WindowDecodeSession(transfer_id=transfer_id, window_id=window_id)
                
                window_session = session.windows[window_id]
                if window_session.is_complete: continue
                
                window_packets = packet_pool.get_packets(transfer_id, window_id)
                
                # Determine K_fountain
                if window_id == manifest.total_windows - 1:
                    window_size = manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes
                else:
                    window_size = manifest.window_size_bytes
                W = (window_size + manifest.chunk_size - 1) // manifest.chunk_size
                num_blocks = (W + manifest.rs_k - 1) // manifest.rs_k
                K_fountain = num_blocks * manifest.rs_n
                
                min_packets = int(K_fountain * 1.05)
                last_attempt = getattr(window_session, "last_attempt_count", 0)
                trigger_interval = 50 if K_fountain < 1000 else 200
                
                if len(window_packets) >= min_packets and (len(window_packets) >= last_attempt + trigger_interval):
                    window_session.last_attempt_count = len(window_packets)
                    logger.info(f"Decoding window {window_id} of {transfer_id} ({len(window_packets)} packets, K={K_fountain})")
                    
                    decoder = FountainDecoderWrapper("lt")
                    decode_result = decoder.decode_window(window_packets, K=K_fountain, chunk_size=manifest.chunk_size)
                    
                    if sum(1 for c in decode_result.chunks if c is not None) > 0:
                        logger.info(f"RS recovery for window {window_id}")
                        rs_decoder = ReedSolomonDecoder(RSConfig(n=manifest.rs_n, k=manifest.rs_k))
                        try:
                            chunks = rs_decoder.decode(decode_result.chunks)
                            reassembler = WindowReassembler(window_id=window_id, chunk_size=manifest.chunk_size, expected_bytes=window_size)
                            for i in range(W):
                                block_id = i // manifest.rs_k
                                chunk_in_block = i % manifest.rs_k
                                chunk_data = chunks[block_id * manifest.rs_n + chunk_in_block]
                                
                                if verify_chunk_merkle(chunk_data, i + (window_id * (manifest.window_size_bytes // manifest.chunk_size)), manifest.merkle_root):
                                    reassembler.add_chunk(i, chunk_data)
                            
                            if reassembler.is_complete():
                                window_session.data = reassembler.get_window_bytes()
                                window_session.is_complete = True
                                logger.info(f"Window {window_id} complete")
                        except Exception as e:
                            logger.warning(f"RS failed: {e}")
                
                # Check for file completion
                if len(session.windows) == manifest.total_windows and all(w.is_complete for w in session.windows.values()):
                    logger.info(f"Reassembling {manifest.file_name}")
                    try:
                        final_file_bytes = b"".join(session.windows[i].data for i in range(manifest.total_windows))
                        if FileVerifier.verify_file(final_file_bytes, manifest.file_size, manifest.file_sha256)["valid"]:
                            logger.info(f"SUCCESS! {manifest.file_name}")
                            storage_writer.store_file(final_file_bytes, manifest, session.received_packets)
                            completed_transfers.add(transfer_id)
                            del active_transfers[transfer_id]
                    except Exception as e:
                        logger.error(f"Reassembly error: {e}")
                        completed_transfers.add(transfer_id)
                        del active_transfers[transfer_id]

    except KeyboardInterrupt:
        pass
    finally:
        receiver.close()
