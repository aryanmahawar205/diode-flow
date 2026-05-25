"""
UDP receiver. recvfrom() only. sendto() never called — ever.
Per-transfer ring buffers to organise incoming packets.
"""
from __future__ import annotations
import logging
import socket
from collections import defaultdict, deque
from common.config import UDP_RECV_BUFFER, MAX_UDP_PAYLOAD, DEFAULT_PORT

logger = logging.getLogger(__name__)


class Receiver:
    def __init__(self, bind_addr: str = "0.0.0.0", port: int = DEFAULT_PORT):
        self._sock   = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, UDP_RECV_BUFFER)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(0.1)
        self._sock.bind((bind_addr, port))
        self.buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=500_000))
        self.raw_queue: deque = deque(maxlen=100_000)
        logger.info(f"Receiver bound to {bind_addr}:{port}")

    def recv_one(self) -> bytes | None:
        """Receive one raw UDP datagram. Returns None on timeout."""
        try:
            data, _ = self._sock.recvfrom(MAX_UDP_PAYLOAD)
            return data
        except socket.timeout:
            return None
        except OSError as e:
            logger.error(f"Socket error: {e}")
            return None

    def close(self):
        self._sock.close()
