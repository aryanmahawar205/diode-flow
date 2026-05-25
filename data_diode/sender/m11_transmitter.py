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
    packets_per_second: int = 10000       # 12 MB/s - safe for Python
    max_packet_size: int = 1472           # MTU - IP/UDP headers


class Transmitter:
    """
    UDP transmitter for encoded packets with efficient rate control.
    """

    def __init__(self, config: TransmitterConfig = None):
        self.config = config or TransmitterConfig()
        self.socket: Optional[socket.socket] = None
        self.packet_count = 0
        self._tokens = self.config.packets_per_second / 10 # Burst size
        self._last_token_update = time.time()

    def _send_raw(self, remote_addr: tuple[str, int], data: bytes) -> None:
        """
        Send a single packet with token-bucket rate limiting.
        """
        if self.socket is None:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Increase OS send buffer
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)

        # Token bucket rate limiting
        if self.config.packets_per_second > 0:
            while self._tokens < 1.0:
                now = time.time()
                elapsed = now - self._last_token_update
                # Refill bucket
                self._tokens = min(
                    self.config.packets_per_second / 10, # Cap burst
                    self._tokens + elapsed * self.config.packets_per_second
                )
                self._last_token_update = now
                if self._tokens < 1.0:
                    # Sleep briefly if bucket still empty (batch sleep)
                    time.sleep(0.001)
            self._tokens -= 1.0
        
        self.socket.sendto(data, remote_addr)
        self.packet_count += 1

    def send_transfer(
        self,
        remote_addr: tuple[str, int],
        manifest_bytes: bytes,
        header_redundancy: int,
        windows_packets: list[list[bytes]],
        transfer_id: str
    ) -> None:
        """
        Orchestrate full transmission sequence.
        1. Manifest x header_redundancy
        2. Window packets (already interleaved)
        3. Footer x 3
        """
        # 1. Manifest
        for _ in range(header_redundancy):
            self._send_raw(remote_addr, manifest_bytes)
            
        # 2. Window packets
        for window_pkts in windows_packets:
            for packet_bytes in window_pkts:
                self._send_raw(remote_addr, packet_bytes)
                
        # 3. Footer
        footer = f"TRANSFER_END:{transfer_id}".encode()
        for _ in range(3):
            self._send_raw(remote_addr, footer)

    def close(self):
        """Close the UDP socket."""
        if self.socket:
            self.socket.close()
            self.socket = None

    def __del__(self):
        self.close()
