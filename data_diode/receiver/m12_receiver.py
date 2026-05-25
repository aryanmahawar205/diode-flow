"""
UDP receiver for encoded packets.
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
    max_packet_size: int = 4096            # Increased to handle any reasonable UDP packet
    receive_buffer_size: int = 16 * 1024 * 1024 # 16MB OS-level buffer


@dataclass
class PacketEntry:
    """Received UDP packet."""
    payload: bytes
    source_addr: tuple[str, int]
    timestamp: float = field(default_factory=time.time)


class Receiver:
    """
    UDP receiver with non-blocking interface.
    """

    def __init__(
        self,
        bind_addr: str = "0.0.0.0",
        bind_port: int = 0,
        config: ReceiverConfig = None
    ):
        self.bind_addr = bind_addr
        self.bind_port = bind_port
        self.config = config or ReceiverConfig()
        self.socket: Optional[socket.socket] = None
        self.actual_port = None

    def _bind_socket(self) -> None:
        if self.socket:
            return

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.config.receive_buffer_size)
        self.socket.setblocking(False)

        self.socket.bind((self.bind_addr, self.bind_port))
        self.actual_port = self.socket.getsockname()[1]
        logger.info(f"Receiver bound to {self.bind_addr}:{self.actual_port}")

    def receive_nonblocking(self) -> Optional[PacketEntry]:
        """Receive one packet without blocking."""
        if self.socket is None:
            self._bind_socket()

        try:
            payload, source_addr = self.socket.recvfrom(self.config.max_packet_size)
            return PacketEntry(payload=payload, source_addr=source_addr)
        except (BlockingIOError, socket.timeout):
            return None
        except OSError as e:
            logger.error(f"Socket error: {e}")
            return None

    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None

    def __del__(self):
        self.close()
