"""
LT (Luby Transform) decoder implementation.

This module implements an LT decoder using belief propagation peeling algorithm
to recover source symbols from encoded packets.

Why belief propagation?
- Iteratively identifies degree-1 (or low-degree) symbols that are XORed with known data.
- "Peeling" removes decoded symbols from remaining encoded packets, reducing their degree.
- Continues until all source symbols are decoded or no degree-1 symbols remain.
- Linear time complexity: O(K * avg_degree).

Key design decisions:
- Bipartite graph stored as: chunks (variable nodes) and packets (check nodes).
- Peeling removes edges and XORs out decoded symbols immediately.
- If graph stalls before all K symbols decoded → returns partial result.
- Caller (m17_rs_decoder) uses RS parity to recover missing chunks.

Implementation references:
- Mackay, D. J. (2005). Fountain codes. IEEE/ACM Trans. Networking.
- Shokrollahi, A. (2006). Raptor codes. IEEE/ACM Trans. Networking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from data_diode.fountain.interface import IFountainDecoder, EncodedPacket, DecodeResult

logger = logging.getLogger(__name__)


@dataclass
class _VariableNode:
    """Represents a source chunk in the Tanner graph."""
    chunk_id: int
    value: bytes | None = None
    is_known: bool = False
    connected_packets: list[int] = field(default_factory=list)


@dataclass
class _CheckNode:
    """Represents an encoded packet in the Tanner graph."""
    packet_id: int
    degree: int
    data: bytearray
    connected_chunks: list[int] = field(default_factory=list)


import numpy as np
import collections

class LTDecoder(IFountainDecoder):
    """LT decoder using belief propagation peeling and numpy XOR."""

    def decode(
        self,
        pool: list[EncodedPacket],
        K: int,
    ) -> DecodeResult:
        """
        Decode source chunks from encoded packet pool using belief propagation.
        """
        if not pool:
            return DecodeResult(
                chunks=[None] * K,
                success=False,
                recovered_count=0,
                missing_ids=list(range(K)),
                packets_used=0,
            )

        if K <= 0:
            raise ValueError("K must be > 0")

        logger.debug(f"LT decode starting: K={K}, pool_size={len(pool)}")

        chunk_size = len(pool[0].data)
        
        # Tanner graph components
        # We use simple structures for speed in Python
        packet_payloads = [np.frombuffer(p.data, dtype=np.uint8).copy() for p in pool]
        packet_chunks = [set(p.chunk_ids) for p in pool]
        
        # chunk_id -> list of packet indices
        chunk_to_packets = collections.defaultdict(list)
        for pi, chunks in enumerate(packet_chunks):
            for cid in chunks:
                if cid < K: # only track source chunks
                    chunk_to_packets[cid].append(pi)

        # Recovered chunks: chunk_id -> np.array
        recovered = {}
        
        # Queue of degree-1 packets
        queue = collections.deque([pi for pi, chunks in enumerate(packet_chunks) if len(chunks) == 1])
        processed_packets = set()

        while queue:
            pi = queue.popleft()
            if pi in processed_packets or len(packet_chunks[pi]) != 1:
                continue
            
            processed_packets.add(pi)
            
            # This packet has degree 1, so it reveals one chunk
            cid = next(iter(packet_chunks[pi]))
            if cid in recovered:
                # Already known, just propagate if needed (shouldn't happen with processed_packets check)
                continue
            
            # Recover chunk
            chunk_val = packet_payloads[pi].copy()
            recovered[cid] = chunk_val
            
            # Propagate: XOR this chunk out of all other packets containing it
            for other_pi in chunk_to_packets[cid]:
                if other_pi == pi or other_pi in processed_packets:
                    continue
                
                if cid in packet_chunks[other_pi]:
                    # XOR out
                    packet_payloads[other_pi] ^= chunk_val
                    # Remove edge
                    packet_chunks[other_pi].discard(cid)
                    
                    # If other packet now has degree 1, add to queue
                    if len(packet_chunks[other_pi]) == 1:
                        queue.append(other_pi)

        # Extract result
        chunks: list[bytes | None] = [None] * K
        missing_ids = []
        for i in range(K):
            if i in recovered:
                chunks[i] = recovered[i].tobytes()
            else:
                missing_ids.append(i)

        success = len(missing_ids) == 0
        
        return DecodeResult(
            chunks=chunks,
            success=success,
            recovered_count=len(recovered),
            missing_ids=missing_ids,
            packets_used=len(pool),
        )
