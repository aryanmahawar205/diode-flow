"""
Tests for UDP networking components.

Coverage:
- sender/m11_transmitter.py
- receiver/m12_receiver.py
- receiver/m13_validator.py
- receiver/m15_pooler.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from sender.m11_transmitter import Transmitter, TransmitterConfig
from receiver.m12_receiver import Receiver, ReceiverConfig, PacketEntry
from receiver.m13_validator import PacketValidator, ManifestValidator, ValidationError
from receiver.m15_pooler import PacketPool
from fountain.interface import EncodedPacket
from common.models import TransferManifest


class TestTransmitter:
    """Test UDP transmitter."""

    def test_transmitter_config_defaults(self):
        """Check transmitter config defaults."""
        config = TransmitterConfig()
        assert config.packets_per_second == 5000
        assert config.max_packet_size == 1472

    def test_transmitter_init(self):
        """Initialize transmitter."""
        tx = Transmitter()
        assert tx.packet_count == 0
        assert tx.config.packets_per_second == 5000

    def test_transmitter_closes_socket(self):
        """Socket cleanup."""
        tx = Transmitter()
        tx.close()
        assert tx.socket is None


class TestReceiver:
    """Test UDP receiver."""

    def test_receiver_config_defaults(self):
        """Check receiver config defaults."""
        config = ReceiverConfig()
        assert config.max_packet_size == 65507

    def test_receiver_init(self):
        """Initialize receiver."""
        rx = Receiver()
        assert rx.socket is None

    def test_receiver_closes_socket(self):
        """Socket cleanup."""
        rx = Receiver()
        rx._bind_socket()
        assert rx.socket is not None
        rx.close()
        assert rx.socket is None


class TestPacketPool:
    """Test packet pooling and deduplication."""

    def test_pool_add_packet(self):
        """Add packet to pool."""
        pool = PacketPool()
        packet = EncodedPacket(
            packet_id=0,
            pass_id=0,
            seed=123,
            degree=5,
            chunk_ids=[0, 1, 2, 3, 4],
            data=b"data",
            source_chunk_count=10
        )

        added = pool.add_packet("tx1", 0, packet)
        assert added
        assert pool.total_packets == 1

    def test_pool_deduplication(self):
        """Duplicate packets rejected."""
        pool = PacketPool()
        packet = EncodedPacket(
            packet_id=0,
            pass_id=0,
            seed=123,
            degree=5,
            chunk_ids=[0, 1, 2, 3, 4],
            data=b"data",
            source_chunk_count=10
        )

        # Add first time
        added1 = pool.add_packet("tx1", 0, packet)
        assert added1

        # Add duplicate
        added2 = pool.add_packet("tx1", 0, packet)
        assert not added2  # Should be rejected

        # Pool size should be 1
        assert pool.total_packets == 1

    def test_pool_get_unified_pool(self):
        """Retrieve packets from pool."""
        pool = PacketPool()
        packet1 = EncodedPacket(0, 0, 123, 1, [0], b"p1", 10)
        packet2 = EncodedPacket(1, 0, 123, 1, [1], b"p2", 10)

        pool.add_packet("tx1", 0, packet1)
        pool.add_packet("tx1", 0, packet2)

        packets = pool.get_unified_pool("tx1", 0)
        assert len(packets) == 2

    def test_pool_clear_transfer(self):
        """Clear all state for a transfer."""
        pool = PacketPool()
        packet = EncodedPacket(0, 0, 123, 1, [0], b"p1", 10)

        pool.add_packet("tx1", 0, packet)
        pool.add_packet("tx1", 1, packet)

        pool.clear_transfer("tx1")
        assert pool.total_packets == 0
        assert "tx1" not in pool.pools
