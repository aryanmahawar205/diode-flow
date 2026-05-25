"""
Aggregates packets from all passes into unified decode pools per window.
Deduplication by (window_id, pass_id, packet_id).
Readiness trigger: pool >= K_prime * 1.05 OR idle timeout.
Stores EncodedPacket directly — no intermediate PooledPacket type.
TTL based on last activity, not oldest packet.
"""
from __future__ import annotations
import logging
import time
from collections import defaultdict
from common.models import EncodedPacket
from common.config import WINDOW_TIMEOUT_S

logger = logging.getLogger(__name__)


class Pooler:
    def __init__(self):
        self._pools    : dict[str, dict[int, dict]] = defaultdict(lambda: defaultdict(dict))
        self._dedup    : dict[str, set]             = defaultdict(set)
        self._activity : dict[str, float]           = {}

    def add(self, transfer_id: str, window_id: int, pkt: EncodedPacket) -> bool:
        key = (window_id, pkt.pass_id, pkt.packet_id)
        if key in self._dedup[transfer_id]:
            return False
        self._pools[transfer_id][window_id][key] = pkt
        self._dedup[transfer_id].add(key)
        self._activity[transfer_id] = time.time()
        return True

    def count(self, transfer_id: str, window_id: int) -> int:
        return len(self._pools.get(transfer_id, {}).get(window_id, {}))

    def is_ready(self, transfer_id: str, window_id: int, K_prime: int) -> bool:
        if self.count(transfer_id, window_id) >= int(K_prime * 1.20):
            return True
        idle = time.time() - self._activity.get(transfer_id, time.time())
        return idle > WINDOW_TIMEOUT_S

    def get_pool(self, transfer_id: str, window_id: int) -> list[EncodedPacket]:
        """Return unified pool from all passes — decoder sees one flat list."""
        return list(self._pools.get(transfer_id, {}).get(window_id, {}).values())

    def clear_window(self, transfer_id: str, window_id: int) -> None:
        if transfer_id in self._pools and window_id in self._pools[transfer_id]:
            # Remove dedup keys for this window
            to_remove = {k for k in self._dedup[transfer_id]
                         if isinstance(k, tuple) and k[0] == window_id}
            self._dedup[transfer_id] -= to_remove
            del self._pools[transfer_id][window_id]
