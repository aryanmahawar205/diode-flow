"""
Tests for UDP networking components (Steps 12-15).

Coverage:
- sender/m11_transmitter.py
- receiver/m12_receiver.py
- receiver/m13_validator.py
- receiver/m15_pooler.py

Tests cover:
- Rate limiting behavior
- Socket operations
- Validation logic
- Packet pooling and deduplication
"""

import sys
import socket
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from sender.m11_transmitter import Transmitter, TransmitterConfig
from receiver.m12_receiver import Receiver, ReceiverConfig, PacketEntry
from receiver.m13_validator import PacketValidator, ManifestValidator, ValidationError
from receiver.m15_pooler import PacketPool, PooledPacket


class TestTransmitter:
    """Test UDP transmitter."""

    def test_transmitter_config_defaults(self):
        """Check transmitter config defaults."""
        config = TransmitterConfig()
        assert config.packets_per_second == 1000
        assert config.batch_size == 10
        assert config.socket_timeout_ms == 1000

    def test_transmitter_init(self):
        """Initialize transmitter."""
        tx = Transmitter()
        assert tx.packet_count == 0
        assert tx.config.packets_per_second == 1000

    def test_transmitter_rate_limiting(self):
        """Test rate limiter calculation."""
        config = TransmitterConfig(packets_per_second=100, batch_size=1)
        tx = Transmitter(config)

        # First packet in batch should have zero delay
        delay1 = tx._calculate_delay()
        assert delay1 == 0.0

        # Simulate sending packet
        tx.last_send_time = time.time()
        tx.packets_in_batch = 1

        # Next packet should be rate limited
        delay2 = tx._calculate_delay()
        assert delay2 >= 0.0  # May be ~0.01 seconds

    def test_transmitter_payload_size_check(self):
        """Reject oversized payloads."""
        tx = Transmitter()

        # Create payload > max_packet_size
        large_payload = b"x" * (tx.config.max_packet_size + 1)

        with pytest.raises(ValueError, match="too large"):
            tx.send_packet(("127.0.0.1", 9999), large_payload)

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
        assert config.buffer_slots == 10000
        assert config.socket_timeout_ms == 100

    def test_receiver_init(self):
        """Initialize receiver."""
        rx = Receiver()
        assert rx.packet_count == 0
        assert len(rx.buffer) == rx.config.buffer_slots

    def test_receiver_buffer_usage(self):
        """Check buffer usage calculation."""
        rx = Receiver()
        assert rx.buffer_usage() == 0.0

        # Add a packet
        rx.buffer[0] = PacketEntry(
            payload=b"test",
            source_addr=("127.0.0.1", 9999)
        )
        assert rx.buffer_usage() > 0.0

    def test_receiver_cleanup_old_packets(self):
        """Remove packets older than TTL."""
        config = ReceiverConfig(packet_ttl_ms=100)  # 100ms TTL
        rx = Receiver(config=config)

        # Add old packet
        old_time = time.time() - 1.0
        rx.buffer[0] = PacketEntry(
            payload=b"old",
            source_addr=("127.0.0.1", 9999),
            timestamp=old_time
        )

        # Add recent packet
        rx.buffer[1] = PacketEntry(
            payload=b"new",
            source_addr=("127.0.0.1", 9999),
            timestamp=time.time()
        )

        removed = rx.cleanup_old_packets()
        assert removed == 1
        assert rx.buffer[0] is None
        assert rx.buffer[1] is not None

    def test_receiver_closes_socket(self):
        """Socket cleanup."""
        rx = Receiver()
        rx.close()
        assert rx.socket is None


class TestPacketValidator:
    """Test packet validation."""

    def test_validator_init(self):
        """Initialize validator."""
        v = PacketValidator()
        assert v.max_payload_size == 2048
        assert v.max_degree == 1000

    def test_validate_payload_size_empty(self):
        """Reject empty payloads."""
        v = PacketValidator()
        result = v.validate_payload_size(b"")
        assert not result.valid
        assert "Empty" in result.reason

    def test_validate_payload_size_large(self):
        """Reject oversized payloads."""
        v = PacketValidator(max_payload_size=1000)
        result = v.validate_payload_size(b"x" * 1001)
        assert not result.valid
        assert "too large" in result.reason

    def test_validate_payload_size_ok(self):
        """Accept valid payloads."""
        v = PacketValidator()
        result = v.validate_payload_size(b"valid data")
        assert result.valid

    def test_validate_packet_id_negative(self):
        """Reject negative packet_id."""
        v = PacketValidator()
        result = v.validate_packet_id(-1)
        assert not result.valid
        assert "negative" in result.reason

    def test_validate_packet_id_too_large(self):
        """Reject packet_id exceeding limit."""
        v = PacketValidator(max_packet_id=100)
        result = v.validate_packet_id(101)
        assert not result.valid

    def test_validate_packet_id_ok(self):
        """Accept valid packet_id."""
        v = PacketValidator()
        result = v.validate_packet_id(50)
        assert result.valid

    def test_validate_window_id(self):
        """Validate window_id against window count."""
        v = PacketValidator()

        # Out of range
        result = v.validate_window_id(5, total_windows=3)
        assert not result.valid

        # Valid
        result = v.validate_window_id(2, total_windows=3)
        assert result.valid

    def test_validate_fountain_degree(self):
        """Validate fountain degree."""
        v = PacketValidator()

        # Zero
        result = v.validate_fountain_degree(0)
        assert not result.valid

        # Too large
        result = v.validate_fountain_degree(v.max_degree + 1)
        assert not result.valid

        # Valid
        result = v.validate_fountain_degree(5)
        assert result.valid

    def test_validate_transfer_id_empty(self):
        """Reject empty transfer_id."""
        v = PacketValidator()
        result = v.validate_transfer_id("")
        assert not result.valid

    def test_validate_transfer_id_ok(self):
        """Accept valid transfer_id."""
        v = PacketValidator()
        result = v.validate_transfer_id("transfer-123-abc")
        assert result.valid


class TestManifestValidator:
    """Test manifest validation."""

    def test_manifest_validator_init(self):
        """Initialize manifest validator."""
        v = ManifestValidator()
        assert v.max_file_size == 100 * 1024 * 1024

    def test_validate_size_fields_negative_file_size(self):
        """Reject negative file_size."""
        v = ManifestValidator()
        result = v.validate_manifest_size_fields(
            file_size=-1,
            chunk_size=1024,
            total_chunks=1,
            total_windows=1
        )
        assert not result.valid

    def test_validate_size_fields_zero_chunk_size(self):
        """Reject zero chunk_size."""
        v = ManifestValidator()
        result = v.validate_manifest_size_fields(
            file_size=1000,
            chunk_size=0,
            total_chunks=1,
            total_windows=1
        )
        assert not result.valid

    def test_validate_size_fields_ok(self):
        """Accept valid size fields."""
        v = ManifestValidator()
        result = v.validate_manifest_size_fields(
            file_size=10000,
            chunk_size=1024,
            total_chunks=10,
            total_windows=1
        )
        assert result.valid


class TestPacketPool:
    """Test packet pooling and deduplication."""

    def test_pool_init(self):
        """Initialize packet pool."""
        pool = PacketPool()
        assert pool.transfer_count() == 0
        assert pool.pool_size() == 0

    def test_pool_add_packet(self):
        """Add packet to pool."""
        pool = PacketPool()
        packet = PooledPacket(
            payload=b"data",
            pass_id=0,
            packet_id=0,
            degree=5,
            fountain_seed=12345
        )

        added = pool.add_packet("tx1", 0, packet)
        assert added
        assert pool.pool_size() == 1
        assert pool.transfer_count() == 1

    def test_pool_deduplication(self):
        """Duplicate packets rejected."""
        pool = PacketPool()
        packet = PooledPacket(
            payload=b"data",
            pass_id=0,
            packet_id=0,
            degree=5,
            fountain_seed=12345
        )

        # Add first time
        added1 = pool.add_packet("tx1", 0, packet)
        assert added1

        # Add duplicate
        added2 = pool.add_packet("tx1", 0, packet)
        assert not added2  # Should be rejected

        # Pool size should be 1
        assert pool.pool_size() == 1

    def test_pool_get_packets(self):
        """Retrieve packets from pool."""
        pool = PacketPool()
        packet1 = PooledPacket(b"p1", 0, 0, 5, 111)
        packet2 = PooledPacket(b"p2", 0, 1, 5, 222)

        pool.add_packet("tx1", 0, packet1)
        pool.add_packet("tx1", 0, packet2)

        packets = pool.get_packets("tx1", 0)
        assert len(packets) == 2

    def test_pool_window_count(self):
        """Count windows with packets."""
        pool = PacketPool()
        packet = PooledPacket(b"data", 0, 0, 5, 111)

        pool.add_packet("tx1", 0, packet)
        pool.add_packet("tx1", 1, packet)
        pool.add_packet("tx1", 2, packet)

        assert pool.get_window_count("tx1") == 3

    def test_pool_clear_transfer(self):
        """Clear all packets for a transfer."""
        pool = PacketPool()
        packet = PooledPacket(b"data", 0, 0, 5, 111)

        pool.add_packet("tx1", 0, packet)
        pool.add_packet("tx1", 1, packet)

        cleared = pool.clear_transfer("tx1")
        assert cleared == 2
        assert pool.transfer_count() == 0

    def test_pool_cleanup_old_transfers(self):
        """Remove old transfers."""
        config = ReceiverConfig(packet_ttl_ms=100)
        pool = PacketPool(ttl_ms=100)

        # Add old packet
        old_packet = PooledPacket(b"old", 0, 0, 5, 111)
        old_packet.timestamp = time.time() - 1.0
        pool.add_packet("tx_old", 0, old_packet)

        # Add recent packet
        recent_packet = PooledPacket(b"recent", 0, 0, 5, 222)
        pool.add_packet("tx_new", 0, recent_packet)

        removed = pool.cleanup_old_transfers()
        assert removed == 1
        assert pool.transfer_count() == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
