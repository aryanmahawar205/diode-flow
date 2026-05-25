"""
Packet pooling and deduplication.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Set, Optional
from fountain.interface import EncodedPacket

logger = logging.getLogger(__name__)

WINDOW_TIMEOUT = 15.0  # seconds to wait before forcing decode
MAX_POOL_SIZE  = 500_000 # hard cap on total packets in RAM


class PacketPool:
    """
    Manages pools of received packets per transfer/window.
    Supports multi-pass unified decoding.
    """

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        # transfer_id -> window_id -> (pass_id, packet_id) -> EncodedPacket
        self.pools: Dict[str, Dict[int, Dict[tuple[int, int], EncodedPacket]]] = {}
        self.last_activity: Dict[str, float] = {}
        self.dedup_sets: Dict[str, Set[tuple[int, int, int]]] = {}
        self.total_packets = 0

    def add_packet(self, transfer_id: str, window_id: int, packet: EncodedPacket) -> bool:
        """Add a packet to the pool with deduplication."""
        logger.debug(f"Adding packet {packet.packet_id} to pool")
        if self.total_packets >= MAX_POOL_SIZE:
            logger.warning("Pool size cap reached, dropping packet")
            return False

        if transfer_id not in self.pools:
            self.pools[transfer_id] = {}
            self.dedup_sets[transfer_id] = set()

        dedup_key = (window_id, packet.pass_id, packet.packet_id)
        if dedup_key in self.dedup_sets[transfer_id]:
            return False

        if window_id not in self.pools[transfer_id]:
            self.pools[transfer_id][window_id] = {}

        self.pools[transfer_id][window_id][(packet.pass_id, packet.packet_id)] = packet
        self.dedup_sets[transfer_id].add(dedup_key)
        self.last_activity[transfer_id] = time.time()
        self.total_packets += 1
        return True

    def is_ready_to_decode(self, transfer_id: str, window_id: int, K_prime: int) -> bool:
        """Check if a window pool is ready for decoding."""
        count = self.get_packet_count(transfer_id, window_id)
        # Use 1.1x threshold + at least 2 extra packets to avoid premature decode on tiny windows
        if count >= max(int(K_prime * 1.10), K_prime + 2):
            return True
        
        if count == 0:
            return False

        idle = time.time() - self.last_activity.get(transfer_id, time.time())
        return idle > WINDOW_TIMEOUT

    def get_unified_pool(self, transfer_id: str, window_id: int) -> list[EncodedPacket]:
        """Return all packets for a window as a flat list."""
        if transfer_id not in self.pools or window_id not in self.pools[transfer_id]:
            return []
        return list(self.pools[transfer_id][window_id].values())

    def get_packet_count(self, transfer_id: str, window_id: int) -> int:
        if transfer_id not in self.pools or window_id not in self.pools[transfer_id]:
            return 0
        return len(self.pools[transfer_id][window_id])

    def clear_window(self, transfer_id: str, window_id: int) -> None:
        """Clear packets for a specific window to free RAM."""
        if transfer_id in self.pools and window_id in self.pools[transfer_id]:
            count = len(self.pools[transfer_id][window_id])
            del self.pools[transfer_id][window_id]
            self.total_packets -= count
            # Note: we don't clear dedup_sets here to prevent re-processing 
            # packets if they arrive late. Dedup set is cleared in clear_transfer.

    def clear_transfer(self, transfer_id: str) -> None:
        """Clear all state for a transfer."""
        if transfer_id in self.pools:
            for window_id in list(self.pools[transfer_id].keys()):
                self.clear_window(transfer_id, window_id)
            del self.pools[transfer_id]
        self.dedup_sets.pop(transfer_id, None)
        self.last_activity.pop(transfer_id, None)

    def cleanup_old_transfers(self) -> int:
        """Remove transfers older than TTL."""
        now = time.time()
        to_remove = [tid for tid, last_at in self.last_activity.items() 
                     if now - last_at > self.ttl_seconds]
        for tid in to_remove:
            self.clear_transfer(tid)
        return len(to_remove)
