"""
UDP receiver for encoded packets.
"""

from __future__ import annotations

import logging
import socket
import time
import json
import struct
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ReceiverConfig:
    """Configuration for UDP receiver."""
    max_packet_size: int = 65507            # Max UDP datagram size
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
        self.transfer_buffers: dict[str, deque[PacketEntry]] = defaultdict(deque)

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
        """Receive one packet without blocking and route to transfer_id buffer."""
        if self.socket is None:
            self._bind_socket()

        try:
            payload, source_addr = self.socket.recvfrom(self.config.max_packet_size)
            packet_entry = PacketEntry(payload=payload, source_addr=source_addr)
            
            # Route to per-transfer-id buffer
            try:
                # Fast-peek at transfer_id without full deserialization
                # Packet format: version(1B) + length(4B) + json(...)
                if len(payload) > 5:
                    length = struct.unpack(">I", payload[1:5])[0]
                    if len(payload) >= 5 + length:
                        json_bytes = payload[5:5+length]
                        d = json.loads(json_bytes.decode("utf-8"))
                        tid = d.get("transfer_id")
                        if tid:
                            self.transfer_buffers[tid].append(packet_entry)
            except Exception:
                pass # Silently fail routing, return raw packet anyway

            return packet_entry
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
