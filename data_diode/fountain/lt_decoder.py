"""
fountain/lt_decoder.py — Ultra-Optimized LT Decoder
"""

from __future__ import annotations

import logging
import collections
import numpy as np
from fountain.interface import IFountainDecoder, EncodedPacket, DecodeResult

logger = logging.getLogger(__name__)

class LTDecoder(IFountainDecoder):
    """LT decoder implementation."""

    def decode(self, packets: list[EncodedPacket], K_prime: int, max_degree: int = 100) -> DecodeResult:
        if not packets:
            return DecodeResult([None] * K_prime, False, 0, list(range(K_prime)), 0)

        # Basic filtering
        safe_packets = [p for p in packets if 1 <= p.degree <= max_degree]
        if not safe_packets:
            return DecodeResult([None] * K_prime, False, 0, list(range(K_prime)), 0)

        chunk_size = len(safe_packets[0].data)
        recovered = [None] * K_prime
        recovered_count = 0
        
        # Graph construction
        packet_payloads = np.zeros((len(safe_packets), chunk_size), dtype=np.uint8)
        packet_chunk_sets = []
        chunk_to_packets = [[] for _ in range(K_prime)]

        for pi, pkt in enumerate(safe_packets):
            packet_payloads[pi] = np.frombuffer(pkt.data, dtype=np.uint8)
            # Use set for fast peeling, but list for initial construction
            cids = {cid for cid in pkt.chunk_ids if 0 <= cid < K_prime}
            packet_chunk_sets.append(cids)
            for cid in cids:
                chunk_to_packets[cid].append(pi)

        # Initial queue: packets with degree 1
        queue = collections.deque([pi for pi, cids in enumerate(packet_chunk_sets) if len(cids) == 1])
        
        while queue:
            pi = queue.popleft()
            if len(packet_chunk_sets[pi]) != 1: continue
            
            chunk_id = next(iter(packet_chunk_sets[pi]))
            if recovered[chunk_id] is not None:
                packet_chunk_sets[pi].clear() # Already recovered, this packet is redundant
                continue
                
            # SUCCESS: Recovered chunk_id
            chunk_arr = packet_payloads[pi].copy()
            recovered[chunk_id] = chunk_arr.tobytes()
            recovered_count += 1
            
            if recovered_count == K_prime: break

            # Peeling: remove this chunk from all other packets that contain it
            for other_pi in chunk_to_packets[chunk_id]:
                other_set = packet_chunk_sets[other_pi]
                if chunk_id in other_set:
                    if len(other_set) > 1:
                        packet_payloads[other_pi] ^= chunk_arr
                        other_set.remove(chunk_id)
                        if len(other_set) == 1:
                            queue.append(other_pi)
                    else:
                        other_set.clear()

        missing_ids = [i for i, c in enumerate(recovered) if c is None]
        return DecodeResult(
            chunks=recovered,
            success=len(missing_ids) == 0,
            recovered_count=recovered_count,
            missing_ids=missing_ids,
            packets_used=len(safe_packets)
        )
