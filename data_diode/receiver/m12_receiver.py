"""
UDP receiver for encoded packets.

Step 13 of Phase 1: receiver/m12_receiver.py

Receives UDP packets into a ring buffer for processing.
Designed for high-loss, one-way channels - no flow control.

Key design:
- Ring buffer: Fixed-size circular buffer (prevents memory exhaustion)
- Non-blocking receive: Single buffer per transfer (or shared pool)
- Packet tracking: Metadata for each received packet
- Timeout handling: Old packets discarded to free buffer slots

Architecture:
- ReceiverConfig: Buffer size, socket bind parameters
- PacketEntry: Stores packet data + metadata (timestamp, source)
- Receiver: Ring buffer with receive() method
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ReceiverConfig:
    """Configuration for UDP receiver."""
    buffer_slots: int = 10000              # Ring buffer size
    socket_timeout_ms: int = 100           # Receive timeout
    max_packet_size: int = 1472            # MTU - IP/UDP headers
    packet_ttl_ms: int = 60000             # Max age before discard


@dataclass
class PacketEntry:
    """Entry in receive ring buffer."""
    payload: bytes
    source_addr: tuple[str, int]
    timestamp: float = field(default_factory=time.time)
    sequence_id: int = 0                   # Optional per-source counter


class Receiver:
    """
    UDP receiver with ring buffer.

    Receives packets and stores them in a circular buffer.
    """

    def __init__(
        self,
        bind_addr: str = "0.0.0.0",
        bind_port: int = 0,
        config: ReceiverConfig = None
    ):
        """
        Initialize receiver.

        Parameters:
            bind_addr: Local address to bind to.
            bind_port: Local port to bind to (0 = any available).
            config: ReceiverConfig with buffer and timeout parameters.
        """
        self.bind_addr = bind_addr
        self.bind_port = bind_port
        self.config = config or ReceiverConfig()

        # Ring buffer
        self.buffer: list[Optional[PacketEntry]] = [
            None for _ in range(self.config.buffer_slots)
        ]
        self.write_index = 0
        self.read_index = 0
        self.packet_count = 0

        # Socket
        self.socket: Optional[socket.socket] = None
        self.actual_port = None

    def _bind_socket(self) -> None:
        """Create and bind UDP socket."""
        if self.socket:
            return

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        timeout_sec = self.config.socket_timeout_ms / 1000.0
        self.socket.settimeout(timeout_sec)

        self.socket.bind((self.bind_addr, self.bind_port))
        self.actual_port = self.socket.getsockname()[1]
        logger.info(f"Receiver bound to {self.bind_addr}:{self.actual_port}")

    def receive_nonblocking(self) -> Optional[PacketEntry]:
        """
        Receive one packet without blocking.

        Returns:
            PacketEntry if packet received, None if no packets or timeout.

        Raises:
            OSError: if socket error occurs.
        """
        if self.socket is None:
            self._bind_socket()

        try:
            payload, source_addr = self.socket.recvfrom(
                self.config.max_packet_size
            )

            # Store in ring buffer
            entry = PacketEntry(
                payload=payload,
                source_addr=source_addr,
                timestamp=time.time()
            )
            self.buffer[self.write_index] = entry
            self.write_index = (self.write_index + 1) % self.config.buffer_slots
            self.packet_count += 1

            return entry

        except socket.timeout:
            # No packet available
            return None
        except OSError as e:
            logger.error(f"Socket error in receive: {e}")
            raise

    def receive_batch(self, max_packets: int = 100) -> list[PacketEntry]:
        """
        Receive up to max_packets in one call.

        Parameters:
            max_packets: Maximum number of packets to receive.

        Returns:
            List of PacketEntry objects (may be empty).
        """
        packets = []
        for _ in range(max_packets):
            entry = self.receive_nonblocking()
            if entry:
                packets.append(entry)
            else:
                break
        return packets

    def buffer_usage(self) -> float:
        """
        Get current buffer usage as fraction.

        Returns:
            Fraction of buffer slots occupied (0.0 to 1.0).
        """
        # Simplified: count non-None entries
        occupied = sum(1 for entry in self.buffer if entry is not None)
        return occupied / len(self.buffer)

    def cleanup_old_packets(self) -> int:
        """
        Remove packets older than TTL.

        Returns:
            Number of packets removed.
        """
        now = time.time()
        ttl_seconds = self.config.packet_ttl_ms / 1000.0
        removed = 0

        for i in range(len(self.buffer)):
            if self.buffer[i] is not None:
                age = now - self.buffer[i].timestamp
                if age > ttl_seconds:
                    self.buffer[i] = None
                    removed += 1

        return removed

    def close(self):
        """Close the UDP socket."""
        if self.socket:
            self.socket.close()
            self.socket = None

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
