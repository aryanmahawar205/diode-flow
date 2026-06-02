"""
UDP receiver. recvfrom() only. sendto() never called — ever.
Per-transfer ring buffers to organise incoming packets.
"""
from __future__ import annotations
import logging
import socket
import threading
import queue
from collections import defaultdict, deque
from common.config import UDP_RECV_BUFFER, MAX_UDP_PAYLOAD, DEFAULT_PORT

logger = logging.getLogger(__name__)


class Receiver:
    def __init__(self, bind_addr: str = "0.0.0.0", port: int = DEFAULT_PORT):
        self._sock   = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024 * 1024)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((bind_addr, port))

        # Use a thread-safe Queue for raw packets
        self.packet_queue = queue.Queue(maxsize=1_000_000)
        self._stop_event = threading.Event()
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)

        logger.info(f"Receiver bound to {bind_addr}:{port}")
        self._recv_thread.start()

    def _recv_loop(self):
        """Background thread to drain the UDP socket as fast as possible."""
        logger.info("Receiver background thread started")
        while not self._stop_event.is_set():
            try:
                # Use a small timeout to check the stop event periodically
                self._sock.settimeout(1.0)
                data, _ = self._sock.recvfrom(MAX_UDP_PAYLOAD)
                try:
                    self.packet_queue.put_nowait(data)
                except queue.Full:
                    # If the queue is full, we are dropping packets at the app level.
                    # This is better than the OS dropping them silently.
                    pass
            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"Socket error in recv_loop: {e}")
                break
        logger.info("Receiver background thread stopped")

    def recv_one(self, timeout: float = 0.1) -> bytes | None:
        """Get one packet from the internal queue. Blocks for timeout seconds."""
        try:
            return self.packet_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        self._stop_event.set()
        self._sock.close()
        self._recv_thread.join(timeout=2.0)
