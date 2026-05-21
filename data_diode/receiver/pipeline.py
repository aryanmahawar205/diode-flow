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
    storage_dir: str = "/tmp/data_diode_storage",
    shared_secret: bytes = b"S" * 32,
    public_key: Optional[bytes] = None,
    quit_event: Optional[any] = None,
) -> None:
    """
    Run the complete receiver pipeline.

    Parameters:
        bind_addr: Local address to bind to.
        bind_port: Local port to bind to.
        storage_dir: Directory to save verified files.
        shared_secret: 32-byte secret for BLAKE3-MAC verification.
        public_key: Ed25519 public key for manifest verification.
        quit_event: Optional event to signal shutdown.
    """
    logger.info(f"Starting receiver on {bind_addr}:{bind_port}")
    
    config = ReceiverConfig(buffer_slots=100000)
    receiver = Receiver(bind_addr, bind_port, config)
    receiver._bind_socket()
    
    packet_validator = PacketValidator()
    manifest_validator = ManifestValidator()
    packet_pool = PacketPool()
    storage_writer = StorageWriter(storage_dir=storage_dir)
    
    # Active transfers: transfer_id -> TransferDecodeSession
    active_transfers: Dict[str, TransferDecodeSession] = {}
    
    # Track completed transfers to avoid reprocessing
    completed_transfers: Set[str] = set()

    try:
        while quit_event is None or not quit_event.is_set():
            # 1. Receive packet
            entry = receiver.receive_nonblocking()
            if not entry:
                # No packet, check for timeouts or sleep briefly
                time.sleep(0.01)
                continue
            
            # 2. Try to identify packet type
            # Simplification: manifest starts with MANIFEST_VERSION byte
            try:
                if entry.payload[0] == MANIFEST_VERSION:
                    # Likely a manifest
                    manifest = deserialize_manifest(entry.payload)
                    
                    if manifest.transfer_id in completed_transfers:
                        continue
                    
                    if manifest.transfer_id not in active_transfers:
                        logger.info(f"Received new manifest for transfer {manifest.transfer_id}: {manifest.file_name}")
                        
                        # Validate manifest
                        val = manifest_validator.validate_manifest_size_fields(
                            manifest.file_size, manifest.chunk_size, 
                            manifest.total_chunks, manifest.total_windows
                        )
                        if not val.valid:
                            logger.error(f"Manifest validation failed: {val.reason}")
                            continue
                        
                        # Verify signature if public key provided
                        if public_key and manifest.ed25519_signature:
                            from data_diode.sender.m9_metadata import verify_manifest_signature, import_public_key
                            if isinstance(public_key, bytes):
                                pub_key_obj = import_public_key(public_key)
                            else:
                                pub_key_obj = public_key
                            
                            # Re-serialize for verification (MAC was computed over proto, 
                            # but here we use the JSON/manual version)
                            # This depends on m10_serializer.serialize_manifest being deterministic
                            manifest_bytes = serialize_manifest(manifest)
                            if not verify_manifest_signature(manifest_bytes, manifest.ed25519_signature, pub_key_obj):
                                logger.error("Manifest signature verification failed!")
                                continue
                        
                        active_transfers[manifest.transfer_id] = TransferDecodeSession(
                            transfer_id=manifest.transfer_id,
                            manifest=manifest
                        )
                    continue

                # Not a manifest, try as a data packet
                packet_proto = deserialize_packet(entry.payload, shared_secret)
                
                # 3. Validate data packet
                transfer_id = packet_proto.transfer_id
                if transfer_id not in active_transfers:
                    # Ignore packets for unknown/completed transfers
                    continue
                
                session = active_transfers[transfer_id]
                manifest = session.manifest
                
                # Multi-level validation
                if not packet_validator.validate_window_id(packet_proto.window_id, manifest.total_windows).valid:
                    continue
                if not packet_validator.validate_fountain_degree(packet_proto.fountain_degree).valid:
                    continue
                # etc.
                
                # 4. Add to pool
                pooled = PooledPacket(
                    payload=packet_proto.payload,
                    pass_id=packet_proto.pass_id,
                    packet_id=packet_proto.packet_id,
                    degree=packet_proto.fountain_degree,
                    fountain_seed=packet_proto.fountain_seed
                )
                packet_pool.add_packet(transfer_id, packet_proto.window_id, pooled)
                session.received_packets += 1
                
                # 5. Check if window ready for decode
                window_packets = packet_pool.get_packets(transfer_id, packet_proto.window_id)
                
                # IMPORTANT: K for fountain MUST match what the sender used.
                # The sender always pads the window to rs_k and then adds parity to rs_n.
                K_fountain = manifest.rs_n
                
                # Trigger decode when we have packets >= K + small overhead
                if len(window_packets) >= K_fountain + 5: # 5% overhead threshold
                    
                    if packet_proto.window_id in session.windows and session.windows[packet_proto.window_id].is_complete:
                        continue

                    logger.info(f"Triggering decode for window {packet_proto.window_id} of {transfer_id} (K_fountain={K_fountain})")
                    
                    # Fountain Decode
                    decoder = FountainDecoderWrapper("lt")
                    decode_result = decoder.decode_window(
                        window_packets, K=K_fountain, chunk_size=manifest.chunk_size
                    )
                    
                    if not decode_result.success:
                        logger.warning(f"Fountain decode failed for window {packet_proto.window_id}, recovered {sum(1 for c in decode_result.chunks if c is not None)}/{K_fountain}")
                    
                    # RS Decode
                    logger.info(f"Step 17: RS Decoder — Recovering missing chunks using parity")
                    rs_config = RSConfig(n=manifest.rs_n, k=manifest.rs_k)
                    rs_decoder = ReedSolomonDecoder(rs_config)
                    
                    try:
                        chunks = rs_decoder.decode(decode_result.chunks)
                    except Exception as e:
                        logger.error(f"RS decode failed: {e}")
                        continue
                    
                    # Reassemble window
                    # Determine actual bytes in this window
                    if packet_proto.window_id == manifest.total_windows - 1:
                        window_size = manifest.file_size % manifest.window_size_bytes or manifest.window_size_bytes
                    else:
                        window_size = manifest.window_size_bytes

                    reassembler = WindowReassembler(
                        window_id=packet_proto.window_id,
                        chunk_size=manifest.chunk_size,
                        expected_bytes=window_size
                    )
                    # Only add the original data chunks
                    chunks_per_window = manifest.total_chunks // manifest.total_windows
                    chunks_in_window = chunks_per_window
                    if packet_proto.window_id == manifest.total_windows - 1:
                        chunks_in_window = manifest.total_chunks - (chunks_per_window * (manifest.total_windows - 1))
                    
                    for i in range(chunks_in_window):
                        if i < len(chunks) and chunks[i] is not None:
                            reassembler.add_chunk(i, chunks[i])
                    
                    if reassembler.is_complete():
                        window_bytes = reassembler.get_window_bytes()
                        session.windows[packet_proto.window_id] = WindowDecodeSession(
                            transfer_id=transfer_id,
                            window_id=packet_proto.window_id,
                            window_manifest=None, # Simplified
                            is_complete=True
                        )
                        session.windows[packet_proto.window_id].data = window_bytes
                        logger.info(f"Window {packet_proto.window_id} complete")
                    
                    # 6. Check if all windows complete
                    if len(session.windows) == manifest.total_windows:
                        logger.info(f"All windows complete for {transfer_id}. Reassembling file...")
                        
                        file_reassembler = FileReassembler()
                        # Sort windows and join
                        ordered_windows = [session.windows[i].data for i in range(manifest.total_windows)]
                        final_file_bytes = b"".join(ordered_windows)
                        
                        # Final Verifier (Step 21)
                        verification = FileVerifier.verify_file(
                            final_file_bytes, manifest.file_size, manifest.file_sha256
                        )
                        
                        if verification["valid"]:
                            logger.info(f"SUCCESS! File {manifest.file_name} verified.")
                            storage_writer.store_file(
                                final_file_bytes, manifest, 
                                packets_received=session.received_packets
                            )
                            completed_transfers.add(transfer_id)
                            del active_transfers[transfer_id]
                        else:
                            logger.error(f"Verification failed for {manifest.file_name}: {verification}")

            except Exception:
                logger.exception("Error processing packet")
                continue

    except KeyboardInterrupt:
        logger.info("Receiver shutting down...")
    finally:
        receiver.close()
