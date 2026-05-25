"""
LT (Luby Transform) decoder implementation.

This module implements an LT decoder using belief propagation peeling algorithm
to recover source symbols from encoded packets.
"""

from __future__ import annotations

import logging
import collections
import numpy as np
from fountain.interface import IFountainDecoder, EncodedPacket, DecodeResult

logger = logging.getLogger(__name__)

class LTDecoder(IFountainDecoder):
    """LT decoder implementation."""

    def decode(self, packets: list[EncodedPacket], K_prime: int,
               max_degree: int = 100) -> DecodeResult:
        """
        Decode source chunks from encoded packet pool.
        """
        # Fix D — Return graceful result on empty pool
        if not packets:
            return DecodeResult(
                chunks=[None] * K_prime, success=False,
                recovered_count=0, missing_ids=list(range(K_prime)), packets_used=0
            )

        # Fix A — Read chunk_ids directly (not re-derive)
        # DoS guard: degree cap
        safe_packets = [p for p in packets if 1 <= p.degree <= max_degree]

        if not safe_packets:
            return DecodeResult(
                chunks=[None] * K_prime, success=False,
                recovered_count=0, missing_ids=list(range(K_prime)), packets_used=0
            )

        # Build graph — read chunk_ids directly from packet
        recovered       = [None] * K_prime
        # Optimization: Store as numpy arrays directly
        packet_payload  = []
        packet_chunks   = []          # list of set[int]
        chunk_to_packets = [set() for _ in range(K_prime)]

        for pi, pkt in enumerate(safe_packets):
            valid_ids = [cid for cid in pkt.chunk_ids if 0 <= cid < K_prime]
            if len(valid_ids) != pkt.degree:
                continue    # malformed packet
            packet_payload.append(np.frombuffer(pkt.data, dtype=np.uint8).copy())
            packet_chunks.append(set(valid_ids))
            cur_pi = len(packet_payload) - 1
            for cid in valid_ids:
                chunk_to_packets[cid].add(cur_pi)

        # Peeling loop
        queue = collections.deque([pi for pi, chunks in enumerate(packet_chunks) if len(chunks) == 1])
        
        while queue:
            pi = queue.popleft()
            if len(packet_chunks[pi]) != 1:
                continue
            
            chunk_id = next(iter(packet_chunks[pi]))
            if recovered[chunk_id] is not None:
                continue
                
            # Recovered!
            # Optimization: payload is already a numpy array
            chunk_arr = packet_payload[pi]
            recovered[chunk_id] = chunk_arr.tobytes()
            
            # Peeling
            for other_pi in chunk_to_packets[chunk_id]:
                if len(packet_chunks[other_pi]) > 1:
                    packet_payload[other_pi] ^= chunk_arr
                    
                    # Fix C — set.discard() instead of list.remove()
                    packet_chunks[other_pi].discard(chunk_id)
                    
                    if len(packet_chunks[other_pi]) == 1:
                        queue.append(other_pi)

        missing_ids = [i for i, c in enumerate(recovered) if c is None]
        recovered_count = K_prime - len(missing_ids)
        
        return DecodeResult(
            chunks=recovered,
            success=len(missing_ids) == 0,
            recovered_count=recovered_count,
            missing_ids=missing_ids,
            packets_used=len(safe_packets)
        )
