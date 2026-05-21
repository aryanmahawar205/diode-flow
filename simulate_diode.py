"""
End-to-end data diode simulator.

Step 19 of Phase 1: simulate_diode.py

Two-process loopback simulator for testing the complete pipeline.
Sender encodes a file, Receiver decodes it.

Usage:
    python simulate_diode.py <input_file> [output_file]

Design:
- Single machine, two processes
- Sender -> UDP loopback (127.0.0.1:port) -> Receiver
- No packet loss (100% reliability test)
- Full pipeline integration test
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent))

from data_diode.common.config import get_profile
from data_diode.sender.m0_manifest import generate_manifest
from data_diode.sender.m2_chunker import chunk_window
from data_diode.sender.m3_merkle import build_merkle_tree
from data_diode.sender.m10_serializer import serialize_manifest
from data_diode.sender.m11_transmitter import Transmitter
from data_diode.fountain.interface import get_encoder
from data_diode.receiver.m12_receiver import Receiver
from data_diode.receiver.m13_validator import PacketValidator, ManifestValidator
from data_diode.receiver.m15_pooler import PacketPool, PooledPacket
from data_diode.receiver.m16_fountain_decoder import FountainDecoderWrapper
from data_diode.receiver.m20_file_reassembler import FileReassembler
from data_diode.receiver.m21_verifier import FileVerifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DataDiodeSimulator:
    """
    Simulates complete data diode pipeline.
    """

    def __init__(self, input_file: str, output_file: Optional[str] = None):
        """
        Initialize simulator.

        Parameters:
            input_file: File to transfer.
            output_file: Output path (default: input_file.recovered).
        """
        self.input_file = input_file
        self.output_file = output_file or f"{input_file}.recovered"

    def run(self) -> bool:
        """
        Run complete simulation.

        Returns:
            True if transfer and verification successful.
        """
        logger.info("=== Data Diode Simulator ===")
        logger.info(f"Input file: {self.input_file}")
        logger.info(f"Output file: {self.output_file}")

        # Step 1: Generate manifest
        logger.info("\n[1] Generating manifest...")
        profile = get_profile(
            file_size=os.path.getsize(self.input_file),
            criticality="standard"
        )
        manifest = generate_manifest(
            self.input_file,
            sender_node_id="simulator-sender",
            profile=profile
        )
        logger.info(f"  Transfer ID: {manifest.transfer_id}")
        logger.info(f"  File size: {manifest.file_size} bytes")
        logger.info(f"  Chunks: {manifest.total_chunks}")
        logger.info(f"  Windows: {manifest.total_windows}")

        # Step 2: Read and chunk file
        logger.info("\n[2] Chunking file...")
        with open(self.input_file, "rb") as f:
            file_data = f.read()

        chunks = []
        window_offset = 0
        for window_id in range(manifest.total_windows):
            window_end = min(
                window_offset + manifest.window_size_bytes,
                len(file_data)
            )
            window_data = file_data[window_offset:window_end]

            result = chunk_window(window_data, manifest.chunk_size)
            chunks.extend(result.chunks)
            logger.info(f"  Window {window_id}: {len(result.chunks)} chunks")

            window_offset = window_end

        logger.info(f"  Total chunks: {len(chunks)}")

        # Step 3: Setup receiver
        logger.info("\n[3] Setting up receiver...")
        rx = Receiver(bind_addr="127.0.0.1", bind_port=0)
        rx._bind_socket()
        logger.info(f"  Receiver listening on {rx.bind_addr}:{rx.actual_port}")

        # Step 4: Send packets
        logger.info("\n[4] Encoding and sending packets...")
        tx = Transmitter()
        encoder = get_encoder("lt")
        pool = PacketPool()

        packet_count = 0
        for pass_id in range(manifest.num_passes):
            packets = encoder.encode(chunks, seed=pass_id * 12345)
            logger.info(f"  Pass {pass_id}: {len(packets)} encoded packets")

            for pkt in packets:
                # Send to receiver
                packet_bytes = pkt.payload  # Simplified: just payload for simulation
                tx.send_packet(
                    (rx.bind_addr, rx.actual_port),
                    packet_bytes
                )
                packet_count += 1

        logger.info(f"  Sent {packet_count} total packets")

        # Step 5: Receive packets
        logger.info("\n[5] Receiving packets...")
        rx.socket.settimeout(5.0)  # 5 second receive timeout
        packets_received = []

        try:
            while True:
                entry = rx.receive_nonblocking()
                if entry:
                    packets_received.append(entry)
                else:
                    time.sleep(0.01)
        except socket.timeout:
            pass

        logger.info(f"  Received {len(packets_received)} packets")

        # Step 6: Decode
        logger.info("\n[6] Decoding packets...")
        decoder_wrapper = FountainDecoderWrapper("lt")

        # Convert received packets to PooledPacket format
        pooled = [
            PooledPacket(
                payload=entry.payload,
                pass_id=0,  # Simplified
                packet_id=i,
                degree=5,  # Dummy
                fountain_seed=12345
            )
            for i, entry in enumerate(packets_received)
        ]

        result = decoder_wrapper.decode_window(
            pooled,
            K=len(chunks),
            chunk_size=manifest.chunk_size
        )

        stats = decoder_wrapper.get_recovery_stats(result)
        logger.info(f"  Recovery: {stats['chunks_recovered']}/{len(result.chunks)}")

        if stats['chunks_recovered'] == 0:
            logger.error("  Decoding failed!")
            return False

        # Step 7: Reassemble
        logger.info("\n[7] Reassembling file...")
        reassembler = FileReassembler()

        try:
            reassembler.add_window_chunks(
                window_id=0,
                chunks=result.chunks,
                chunk_size=manifest.chunk_size,
                padding_length=0
            )

            reassembled = reassembler.reassemble_file(
                total_windows=1,  # Simplified single window
                chunk_size=manifest.chunk_size,
                expected_file_size=manifest.file_size
            )

            if not reassembled:
                logger.error("  Reassembly failed!")
                return False

            logger.info(f"  Reassembled {len(reassembled)} bytes")
        except Exception as e:
            logger.error(f"  Reassembly error: {e}")
            return False

        # Step 8: Verify
        logger.info("\n[8] Verifying...")
        verification = FileVerifier.verify_file(
            reassembled,
            manifest.file_size,
            manifest.file_sha256
        )

        logger.info(f"  Size match: {verification['size_match']}")
        logger.info(f"  Hash match: {verification['hash_match']}")
        logger.info(f"  Valid: {verification['valid']}")

        if not verification['valid']:
            logger.error("  Verification failed!")
            return False

        # Step 9: Write output
        logger.info("\n[9] Writing output file...")
        try:
            with open(self.output_file, "wb") as f:
                f.write(reassembled)
            logger.info(f"  Written to {self.output_file}")
        except IOError as e:
            logger.error(f"  Write failed: {e}")
            return False

        logger.info("\n=== SUCCESS ===")
        return True


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Data Diode Simulator - End-to-end transfer test"
    )
    parser.add_argument("input_file", help="File to transfer")
    parser.add_argument("--output", help="Output file path (default: input.recovered)")

    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Error: {args.input_file} not found")
        sys.exit(1)

    simulator = DataDiodeSimulator(args.input_file, args.output)
    success = simulator.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()