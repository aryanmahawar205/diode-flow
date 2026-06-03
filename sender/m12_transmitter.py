"""
UDP transmitter. Fire-and-forget. Never receives.
Rate control via sleep — caller does not manage timing.
send_transfer() handles the full transmission sequence.
"""
from __future__ import annotations
import logging
import socket
import time
import random
from common.config import UDP_SEND_BUFFER, MAX_UDP_PAYLOAD

logger = logging.getLogger(__name__)


class Transmitter:
    def __init__(
        self,
        packets_per_second: int = 10000,
        packet_loss_rate: float = 0.0,
    ):
        self._pps = packets_per_second
        self._gap = 1.0 / packets_per_second if packets_per_second > 0 else 0

        self._loss_rate = packet_loss_rate

        self._sock = None
        self._sent = 0
        self._dropped = 0

    def _ensure_socket(self):
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, UDP_SEND_BUFFER)

    def send_raw(self, addr: tuple, data: bytes) -> None:
        if len(data) > MAX_UDP_PAYLOAD:
            raise ValueError(f"Packet too large: {len(data)} > {MAX_UDP_PAYLOAD}")
        self._ensure_socket()
        if self._loss_rate > 0.0:
            if random.random() < self._loss_rate:
                self._dropped += 1
                return
        self._sock.sendto(data, addr)
        self._sent += 1

        # Batch throttling instead of sleeping every packet
        if self._gap and self._sent % 1000 == 0:
            time.sleep(self._gap * 1000)

    def send_transfer(self, addr: tuple, manifest_bytes: bytes,
                      header_redundancy: int,
                      window_packet_lists: list[list[bytes]]) -> dict:
        """
        Complete transfer sequence:
        1. Manifest × header_redundancy
        2. For each window: all its serialized packets
        3. Footer × 3
        """
        stats = {"manifest_sends": 0, "packet_sends": 0, "bytes_sent": 0}

        # Phase 0: manifest
        for _ in range(header_redundancy):
            self.send_raw(addr, manifest_bytes)
            stats["manifest_sends"] += 1

        # Phase 1..N: window data
        for window_packets in window_packet_lists:
            for pkt_bytes in window_packets:
                self.send_raw(addr, pkt_bytes)
                stats["packet_sends"] += 1
                stats["bytes_sent"]   += len(pkt_bytes)

        # Footer
        footer = b"DIODE_TRANSFER_END"
        for _ in range(3):
            self.send_raw(addr, footer)

        logger.info(f"Transmitted={self._sent:,} "f"Dropped={self._dropped:,} "f"Loss={self._loss_rate*100:.1f}%")
        return stats

    def close(self):
        logger.info(
            f"Packet-loss simulator: "
            f"dropped={self._dropped:,} "
            f"sent={self._sent:,}"
        )

        if self._sock:
            self._sock.close()
            self._sock = None