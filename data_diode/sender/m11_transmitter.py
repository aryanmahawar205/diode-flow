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
    packets_per_second: int = 2000        # Rate limit
    batch_size: int = 20                  # Packets per batch before sleeping
    socket_timeout_ms: int = 1000         # Socket timeout
    max_packet_size: int = 1472           # MTU - IP/UDP headers


class Transmitter:
    """
    UDP transmitter for encoded packets with precise rate control.
    """

    def __init__(self, config: TransmitterConfig = None):
        """
        Initialize transmitter.
        """
        self.config = config or TransmitterConfig()
        self.socket: Optional[socket.socket] = None
        self.packet_count = 0

    def send_transfer(self, remote_addr: tuple[str, int], packet_payloads: list[bytes]) -> int:
        """
        Send a list of packets with rate-limiting sleep.
        """
        if self.socket is None:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)

        delay_per_packet = 1.0 / self.config.packets_per_second
        total_sent = 0

        for payload in packet_payloads:
            if len(payload) > self.config.max_packet_size:
                logger.warning(f"Packet too large ({len(payload)}), skipping")
                continue

            start_time = time.time()
            self.socket.sendto(payload, remote_addr)
            total_sent += 1
            self.packet_count += 1

            # Sleep to maintain rate
            elapsed = time.time() - start_time
            sleep_time = max(0.0, delay_per_packet - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        return total_sent

    def close(self):
        """Close the UDP socket."""
        if self.socket:
            self.socket.close()
            self.socket = None

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
