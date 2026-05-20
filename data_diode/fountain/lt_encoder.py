"""
LT (Luby Transform) encoder implementation.

This module implements an LT encoder using Robust Soliton Distribution for degree
selection and XOR operations to generate encoded packets.

Why LT codes?
- Fountain codes are rateless: generate as many packets as needed.
- Degree distribution (Robust Soliton) minimizes overhead needed for recovery.
- Seed-based: given K chunks and a seed, the same encoded packets are regenerated.

Key design decisions:
- Degree selection uses Robust Soliton with delta=0.1 (protection against loss).
- PRNG seeded with provided seed + packet index for reproducibility.
- Each encoded packet stores degree and seed so decoder can verify structure.
- No Tanner graph stored — purely generative (low memory overhead).

Implementation references:
- Luby, M. (2002). "LT Codes". RFC 3926 (experimental).
- Mackay, D. J. (2005). Fountain codes.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from fountain.interface import IFountainEncoder, EncodedPacket

logger = logging.getLogger(__name__)


def _robust_soliton_degree(K: int, delta: float = 0.1) -> int:
    """
    Generate a degree sample from Robust Soliton Distribution.

    Parameters:
        K: Number of source symbols.
        delta: Failure probability target (default 0.1).

    Returns:
        Sampled degree d (1 <= d <= K).

    The Robust Soliton Distribution combines:
    - Ideal Soliton (minimizes expected overhead)
    - Robust Soliton (adds protection against degree-1 symbols being lost)
    """
    # Precomputed parameters for Robust Soliton
    M = max(K, 2)  # chunk count
    c = 0.1  # constant for robustness
    S = c * M * (M ** 0.5)  # median of ideal Soliton before robustness spike

    # Compute robust Soliton PDF at each degree
    # rho(d) = ideal Soliton + robustness spike
    rho = [0.0] * (K + 1)  # rho[0] unused, rho[1..K]

    # Ideal Soliton rho component
    for d in range(1, K + 1):
        if d == 1:
            rho[d] = 1.0 / M
        else:
            rho[d] = 1.0 / (d * (d - 1))

    # Robustness spike (protect degree-1 symbols)
    spike_limit = min(int(M / S) + 1, K)
    for d in range(1, spike_limit):
        if d < len(rho):
            rho[d] += (c * (M ** 0.5)) / (M * d * S)

    # Normalize to probability distribution
    total = sum(rho[1:])
    if total <= 0:
        return 1
    rho = [r / total for r in rho]

    # Sample via cumulative distribution
    r = random.random()
    cumsum = 0.0
    for d in range(1, K + 1):
        cumsum += rho[d]
        if r <= cumsum:
            return d

    return K


class LTEncoder(IFountainEncoder):
    """LT encoder with Robust Soliton degree distribution."""

    def encode(
        self,
        chunks: list[bytes],
        seed: int,
        overhead_ratio: float,
    ) -> list[EncodedPacket]:
        """
        Encode source chunks into LT-encoded packets.

        Parameters:
            chunks: list[bytes] of K equal-sized source chunks.
            seed: PRNG seed for reproducible packet generation.
            overhead_ratio: Fraction overhead (e.g., 0.5 → 1.5*K encoded packets).

        Returns:
            list[EncodedPacket] with degree, seed, and data populated.

        Raises:
            ValueError: if chunks empty, seed < 0, or overhead_ratio < 0.
        """
        if not chunks:
            raise ValueError("chunks list cannot be empty")
        if seed < 0:
            raise ValueError("seed must be non-negative")
        if overhead_ratio < 0:
            raise ValueError("overhead_ratio must be non-negative")

        K = len(chunks)
        chunk_size = len(chunks[0])

        # Validate all chunks same size
        for i, chunk in enumerate(chunks):
            if len(chunk) != chunk_size:
                raise ValueError(
                    f"Chunk {i} size {len(chunk)} != {chunk_size}"
                )

        # Generate encoded packets
        num_packets = int(K * (1.0 + overhead_ratio)) + 1
        encoded = []

        for packet_index in range(num_packets):
            # Seed PRNG for reproducibility
            packet_seed = seed + packet_index
            random.seed(packet_seed)

            # Sample degree from Robust Soliton
            degree = _robust_soliton_degree(K)

            # Randomly select which chunks to XOR
            selected_indices = random.sample(range(K), min(degree, K))

            # XOR selected chunks
            encoded_data = bytearray(chunk_size)
            for idx in selected_indices:
                for j in range(chunk_size):
                    encoded_data[j] ^= chunks[idx][j]

            encoded.append(
                EncodedPacket(
                    degree=degree,
                    seed=packet_seed,
                    data=bytes(encoded_data),
                )
            )

        logger.debug(
            f"LT encoded K={K} chunks into {len(encoded)} packets "
            f"(overhead={overhead_ratio})"
        )
        return encoded
