"""
UDP transmitter for encoded packets.
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
    packets_per_second: int = 5000        # Rate limit (increased for Phase 2)
    max_packet_size: int = 1472           # MTU - IP/UDP headers


class Transmitter:
    """
    UDP transmitter for encoded packets with sleep-based rate control.
    """

    def __init__(self, config: TransmitterConfig = None):
        self.config = config or TransmitterConfig()
        self.socket: Optional[socket.socket] = None
        self.packet_count = 0
        self._last_send_time = 0.0

    def _send_raw(self, remote_addr: tuple[str, int], data: bytes) -> None:
        """
        Send a single packet with sleep-based rate limiting.
        """
        if self.socket is None:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)

        if len(data) > self.config.max_packet_size:
            logger.warning(f"Packet too large ({len(data)}), sending anyway (will likely fragment)")

        # Rate control
        delay = 1.0 / self.config.packets_per_second
        now = time.time()
        elapsed = now - self._last_send_time
        sleep_time = max(0.0, delay - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

        self.socket.sendto(data, remote_addr)
        self._last_send_time = time.time()
        self.packet_count += 1

    def send_transfer(self, remote_addr: tuple[str, int], packet_payloads: list[bytes]) -> int:
        """Legacy wrapper for list of payloads."""
        for payload in packet_payloads:
            self._send_raw(remote_addr, payload)
        return len(packet_payloads)

    def close(self):
        """Close the UDP socket."""
        if self.socket:
            self.socket.close()
            self.socket = None

    def __del__(self):
        self.close()
