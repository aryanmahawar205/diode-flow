"""
UDP transmitter for encoded packets.

Step 12 of Phase 1: sender/m11_transmitter.py

Sends fountain-encoded packets over UDP with configurable rate limiting.
Designed for one-way transmission - no acknowledgments or retries needed.

Key design:
- Rate limiting: packets per second (configurable per transfer profile)
- Batching: send multiple packets per socket write when possible
- Fire-and-forget: no acknowledgments, no timeouts, pure push model
- Socket reuse: single socket per transfer (or share across transfers)
- No fragmentation: packets fit in single UDP datagram (~1472 bytes)

Architecture:
- TransmitterConfig: Rate, batch size, timeout
- Transmitter: Maintains UDP socket, applies rate limiter
- send_packet(): Non-blocking send with rate limiting
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TransmitterConfig:
    """Configuration for UDP transmitter."""
    packets_per_second: int = 1000        # Rate limit
    batch_size: int = 10                  # Packets per batch
    socket_timeout_ms: int = 1000         # Socket timeout
    max_packet_size: int = 1472           # MTU - IP/UDP headers


class Transmitter:
    """
    UDP transmitter for encoded packets.

    Rate limits packet transmission and handles socket operations.
    """

    def __init__(self, config: TransmitterConfig = None):
        """
        Initialize transmitter.

        Parameters:
            config: TransmitterConfig with rate and batching parameters.
        """
        self.config = config or TransmitterConfig()
        self.socket: Optional[socket.socket] = None
        self.packet_count = 0
        self.last_send_time = 0.0
        self.packets_in_batch = 0

    def _calculate_delay(self) -> float:
        """
        Calculate delay before next packet send.

        Returns:
            Delay in seconds.

        Implements token bucket rate limiting:
        - Tokens replenish at packets_per_second rate
        - Each packet costs 1 token
        - Max burst: batch_size packets
        """
        if self.config.packets_per_second <= 0:
            return 0.0

        ideal_interval = 1.0 / self.config.packets_per_second
        time_since_last = time.time() - self.last_send_time

        if self.packets_in_batch < self.config.batch_size:
            # Still have burst capacity
            return 0.0

        # Back off until we've waited ideal_interval
        return max(0.0, ideal_interval - time_since_last)

    def send_packet(self, remote_addr: tuple[str, int], payload: bytes) -> int:
        """
        Send a packet to remote address with rate limiting.

        Parameters:
            remote_addr: Tuple of (host, port).
            payload: Packet bytes to send.

        Returns:
            Bytes sent, or -1 if blocked by rate limiter.

        Raises:
            OSError: if socket error occurs.
            ValueError: if payload too large.
        """
        if len(payload) > self.config.max_packet_size:
            raise ValueError(
                f"Payload too large: {len(payload)} > {self.config.max_packet_size}"
            )

        # Rate limiting
        delay = self._calculate_delay()
        if delay > 0:
            return -1  # Rate limited, caller should retry

        # Reset batch counter periodically
        now = time.time()
        if now - self.last_send_time > 1.0:
            self.packets_in_batch = 0
            self.last_send_time = now

        # Create socket if needed
        if self.socket is None:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            timeout_sec = self.config.socket_timeout_ms / 1000.0
            self.socket.settimeout(timeout_sec)

        # Send
        try:
            sent = self.socket.sendto(payload, remote_addr)
            self.packet_count += 1
            self.packets_in_batch += 1
            self.last_send_time = time.time()
            return sent
        except socket.timeout:
            logger.warning(f"Socket timeout sending to {remote_addr}")
            return -1
        except OSError as e:
            logger.error(f"Socket error sending to {remote_addr}: {e}")
            raise

    def close(self):
        """Close the UDP socket."""
        if self.socket:
            self.socket.close()
            self.socket = None

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
