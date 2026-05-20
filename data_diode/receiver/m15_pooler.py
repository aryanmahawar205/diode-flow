"""
Packet pooling and deduplication.

Step 15 of Phase 1: receiver/m15_pooler.py

Pools received packets by transfer_id and window_id.
Performs multi-pass deduplication to eliminate duplicate packets.

Key design:
- Pool structure: Dict[transfer_id] -> Dict[window_id] -> set of packets
- Deduplication: Track (pass_id, packet_id) tuple across passes
- Multi-pass support: Different passes may have different packets for same output
- Memory management: Old transfers purged after TTL

Architecture:
- PacketPool: Thread-safe pool with get/add operations
- PoolEntry: Metadata per pooled packet (timestamp, pass, id)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class PooledPacket:
    """Packet stored in pool."""
    payload: bytes
    pass_id: int
    packet_id: int
    degree: int
    fountain_seed: int
    timestamp: float = field(default_factory=time.time)


class PacketPool:
    """
    Manages pools of received packets per transfer/window.

    Structure:
    transfer_id -> window_id -> set of PooledPacket
    """

    def __init__(self, ttl_ms: int = 300000):
        """
        Initialize packet pool.

        Parameters:
            ttl_ms: Time-to-live for transfers (milliseconds).
        """
        self.ttl_ms = ttl_ms
        self.pools: Dict[str, Dict[int, list[PooledPacket]]] = {}
        self.dedup_sets: Dict[str, Set[tuple[int, int, int]]] = {}

    def add_packet(
        self,
        transfer_id: str,
        window_id: int,
        packet: PooledPacket
    ) -> bool:
        """
        Add a packet to the pool.

        Parameters:
            transfer_id: Transfer identifier.
            window_id: Window number.
            packet: PooledPacket to add.

        Returns:
            True if packet added, False if duplicate.
        """
        # Initialize transfer if needed
        if transfer_id not in self.pools:
            self.pools[transfer_id] = {}
            self.dedup_sets[transfer_id] = set()

        # Check for duplicate
        dedup_key = (window_id, packet.pass_id, packet.packet_id)
        if dedup_key in self.dedup_sets[transfer_id]:
            logger.debug(f"Duplicate packet: {transfer_id}[{window_id}] pass={packet.pass_id} id={packet.packet_id}")
            return False

        # Add to pool
        if window_id not in self.pools[transfer_id]:
            self.pools[transfer_id][window_id] = []

        self.pools[transfer_id][window_id].append(packet)
        self.dedup_sets[transfer_id].add(dedup_key)

        return True

    def get_packets(
        self,
        transfer_id: str,
        window_id: int
    ) -> list[PooledPacket]:
        """
        Get all packets for a window.

        Parameters:
            transfer_id: Transfer identifier.
            window_id: Window number.

        Returns:
            List of PooledPacket objects (may be empty).
        """
        if transfer_id not in self.pools:
            return []

        if window_id not in self.pools[transfer_id]:
            return []

        return self.pools[transfer_id][window_id]

    def get_window_count(self, transfer_id: str) -> int:
        """
        Get number of windows with packets for a transfer.

        Parameters:
            transfer_id: Transfer identifier.

        Returns:
            Number of windows.
        """
        if transfer_id not in self.pools:
            return 0

        return len(self.pools[transfer_id])

    def get_packet_count(self, transfer_id: str, window_id: int) -> int:
        """
        Get packet count for a window.

        Parameters:
            transfer_id: Transfer identifier.
            window_id: Window number.

        Returns:
            Number of packets in pool for this window.
        """
        return len(self.get_packets(transfer_id, window_id))

    def cleanup_old_transfers(self) -> int:
        """
        Remove transfers older than TTL.

        Returns:
            Number of transfers removed.
        """
        now = time.time()
        ttl_seconds = self.ttl_ms / 1000.0
        to_remove = []

        for transfer_id in self.pools:
            if not self.pools[transfer_id]:
                to_remove.append(transfer_id)
                continue

            # Check oldest packet in transfer
            oldest_time = min(
                min((p.timestamp for p in packets) or [now])
                for packets in self.pools[transfer_id].values()
            )

            age = now - oldest_time
            if age > ttl_seconds:
                to_remove.append(transfer_id)

        for transfer_id in to_remove:
            del self.pools[transfer_id]
            del self.dedup_sets[transfer_id]

        return len(to_remove)

    def clear_transfer(self, transfer_id: str) -> int:
        """
        Clear all packets for a transfer.

        Parameters:
            transfer_id: Transfer identifier.

        Returns:
            Number of packets cleared.
        """
        if transfer_id not in self.pools:
            return 0

        total = sum(
            len(packets)
            for packets in self.pools[transfer_id].values()
        )

        del self.pools[transfer_id]
        del self.dedup_sets[transfer_id]

        return total

    def pool_size(self) -> int:
        """
        Get total number of packets in pool.

        Returns:
            Total packets across all transfers/windows.
        """
        total = 0
        for transfer_dict in self.pools.values():
            for packets in transfer_dict.values():
                total += len(packets)
        return total

    def transfer_count(self) -> int:
        """Get number of active transfers in pool."""
        return len(self.pools)
