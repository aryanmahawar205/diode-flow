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


class LTDecoder(IFountainDecoder):
    """LT decoder using belief propagation peeling."""

    def decode(
        self,
        pool: list[EncodedPacket],
        K: int,
    ) -> DecodeResult:
        """
        Decode source chunks from encoded packet pool using belief propagation.

        Parameters:
            pool: list[EncodedPacket] from network or multi-pass.
            K: Number of source symbols to recover.

        Returns:
            DecodeResult with chunks (list[bytes | None]) and missing_ids.

        Raises:
            ValueError: if pool empty or K <= 0.
        """
        if not pool:
            raise ValueError("packet pool cannot be empty")
        if K <= 0:
            raise ValueError("K must be > 0")

        logger.debug(f"LT decode starting: K={K}, pool_size={len(pool)}")

        # Determine chunk size from first packet
        chunk_size = len(pool[0].data)

        # Initialize variable nodes (source chunks)
        var_nodes: dict[int, _VariableNode] = {
            i: _VariableNode(chunk_id=i)
            for i in range(K)
        }

        # Initialize check nodes (encoded packets)
        check_nodes: dict[int, _CheckNode] = {}
        for packet_id, packet in enumerate(pool):
            check_nodes[packet_id] = _CheckNode(
                packet_id=packet_id,
                degree=packet.degree,
                data=bytearray(packet.data),
                connected_chunks=[],
            )

        # Build bipartite graph: reconstruct chunk indices from seed
        self._build_graph(
            var_nodes=var_nodes,
            check_nodes=check_nodes,
            pool=pool,
            K=K,
        )

        # Peeling decoder: iteratively resolve degree-1 symbols
        self._peel(
            var_nodes=var_nodes,
            check_nodes=check_nodes,
            chunk_size=chunk_size,
        )

        # Extract result
        chunks: list[bytes | None] = [None] * K
        missing_ids: list[int] = []

        for i in range(K):
            if var_nodes[i].is_known:
                chunks[i] = var_nodes[i].value
            else:
                missing_ids.append(i)

        success = len(missing_ids) == 0

        logger.debug(
            f"LT decode result: {K - len(missing_ids)}/{K} chunks recovered, "
            f"missing={len(missing_ids)}, success={success}"
        )

        return DecodeResult(
            chunks=chunks,
            missing_ids=missing_ids,
            success=success,
        )

    def _build_graph(
        self,
        var_nodes: dict[int, _VariableNode],
        check_nodes: dict[int, _CheckNode],
        pool: list[EncodedPacket],
        K: int,
    ) -> None:
        """
        Rebuild the bipartite graph from encoded packets by resampling chunk indices.
        """
        import random

        for packet_id, packet in enumerate(pool):
            # Re-seed PRNG with packet seed to regenerate the same chunk indices
            rng = random.Random(packet.seed)

            # Skip the first value which was used for degree sampling in the encoder
            _ = rng.random()
            
            # Use the degree from the packet directly
            degree = packet.degree

            # Select same chunks as encoder
            selected_indices = rng.sample(range(K), min(degree, K))

            # Update graph edges
            check_nodes[packet_id].connected_chunks = selected_indices
            check_nodes[packet_id].degree = len(selected_indices)

            for chunk_id in selected_indices:
                var_nodes[chunk_id].connected_packets.append(packet_id)

    def _peel(
        self,
        var_nodes: dict[int, _VariableNode],
        check_nodes: dict[int, _CheckNode],
        chunk_size: int,
    ) -> None:
        """
        Iteratively peel degree-1 variables and propagate values through graph.

        When a variable is resolved:
        1. All connected check nodes have that variable's value XORed out.
        2. Those check nodes' degrees decrease.
        3. If a check node's degree becomes 1, the last connected variable is known.

        Parameters:
            var_nodes: Variable nodes to decode.
            check_nodes: Check nodes (encoded packets).
            chunk_size: Size of each chunk in bytes.
        """
        import collections

        # Queue of known variables needing propagation
        queue = collections.deque()

        # Find initial degree-1 packets (whose only chunk can be directly solved)
        for packet_id, check in check_nodes.items():
            if check.degree == 1:
                chunk_id = check.connected_chunks[0]
                if not var_nodes[chunk_id].is_known:
                    # Single chunk XOR encoded: chunk == packet.data
                    var_nodes[chunk_id].value = bytes(check.data)
                    var_nodes[chunk_id].is_known = True
                    queue.append(chunk_id)

        # Belief propagation peeling
        while queue:
            chunk_id = queue.popleft()
            chunk_val = var_nodes[chunk_id].value

            # XOR this chunk out of all connected packets
            for packet_id in var_nodes[chunk_id].connected_packets:
                check = check_nodes[packet_id]

                # XOR chunk_val into packet data
                for j in range(chunk_size):
                    check.data[j] ^= chunk_val[j]

                # Remove edge and decrement degree
                check.connected_chunks.remove(chunk_id)
                check.degree -= 1

                # If packet now has degree 1, resolve its last chunk
                if check.degree == 1:
                    last_chunk_id = check.connected_chunks[0]
                    if not var_nodes[last_chunk_id].is_known:
                        var_nodes[last_chunk_id].value = bytes(check.data)
                        var_nodes[last_chunk_id].is_known = True
                        queue.append(last_chunk_id)
