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


from data_diode.fountain.interface import EncodedPacket

class PacketPool:
    """
    Manages pools of received packets per transfer/window.
    Supports multi-pass unified decoding.
    """

    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize packet pool.
        """
        self.ttl_seconds = ttl_seconds
        # transfer_id -> window_id -> (pass_id, packet_id) -> EncodedPacket
        self.pools: Dict[str, Dict[int, Dict[tuple[int, int], EncodedPacket]]] = {}
        self.last_activity: Dict[str, float] = {}
        self.dedup_sets: Dict[str, Set[tuple[int, int, int]]] = {}

    def add_packet(
        self,
        transfer_id: str,
        window_id: int,
        packet: EncodedPacket
    ) -> bool:
        """
        Add a packet to the pool.
        """
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

        return True

    def is_ready_to_decode(self, transfer_id: str, window_id: int, K_prime: int, timeout: float = 5.0) -> bool:
        """
        Check if a window pool is ready for decoding.
        Ready if count >= K_prime * 1.05 OR idle for timeout seconds.
        """
        count = self.get_packet_count(transfer_id, window_id)
        if count >= int(K_prime * 1.05) + 1:
            return True
        
        idle_seconds = time.time() - self.last_activity.get(transfer_id, 0)
        if count > 0 and idle_seconds > timeout:
            return True
            
        return False

    def get_unified_pool(self, transfer_id: str, window_id: int) -> list[EncodedPacket]:
        """Return all packets for a window as a flat list."""
        if transfer_id not in self.pools or window_id not in self.pools[transfer_id]:
            return []
        return list(self.pools[transfer_id][window_id].values())

    def get_packet_count(self, transfer_id: str, window_id: int) -> int:
        """Get packet count for a window."""
        if transfer_id not in self.pools or window_id not in self.pools[transfer_id]:
            return 0
        return len(self.pools[transfer_id][window_id])

    def cleanup_old_transfers(self) -> int:
        """Remove transfers older than TTL."""
        now = time.time()
        to_remove = []

        for tid, last_at in self.last_activity.items():
            if now - last_at > self.ttl_seconds:
                to_remove.append(tid)

        for tid in to_remove:
            self.clear_transfer(tid)

        return len(to_remove)

    def clear_transfer(self, transfer_id: str) -> int:
        """Clear all packets for a transfer."""
        if transfer_id not in self.pools:
            return 0
        
        count = len(self.dedup_sets.get(transfer_id, set()))
        self.pools.pop(transfer_id, None)
        self.dedup_sets.pop(transfer_id, None)
        self.last_activity.pop(transfer_id, None)
        return count

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
