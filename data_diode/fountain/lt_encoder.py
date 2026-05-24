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
import math
from dataclasses import dataclass

from data_diode.fountain.interface import IFountainEncoder, EncodedPacket

logger = logging.getLogger(__name__)


import numpy as np

# Global cache for Robust Soliton distributions to avoid re-calculation
_SOLITON_CACHE: dict[int, list[float]] = {}


def _robust_soliton(K: int, c: float = 0.03, delta: float = 0.02) -> list[float]:
    """
    Standard Robust Soliton Distribution.
    
    Parameters:
        K: Number of source symbols.
        c: Constant (default 0.03).
        delta: Failure probability (default 0.02).
    """
    if K in _SOLITON_CACHE:
        return _SOLITON_CACHE[K]

    R = c * math.log(K / delta) * math.sqrt(K)
    pivot = min(K, max(1, int(math.floor(K / R))))

    # Ideal Soliton distribution rho(d)
    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))

    # Correction term tau(d)
    tau = [0.0] * (K + 1)
    for d in range(1, pivot):
        tau[d] = R / (d * K)
    if pivot >= 1:
        tau[pivot] = (R * math.log(R / delta)) / K

    # Combined distribution mu(d)
    mu_raw = [rho[d] + tau[d] for d in range(K + 1)]
    Z = sum(mu_raw[1:])
    mu = [0.0] + [mu_raw[d] / Z for d in range(1, K + 1)]

    _SOLITON_CACHE[K] = mu
    return mu


def _sample_degree(K: int, rng: random.Random) -> int:
    """Sample a degree from Robust Soliton Distribution."""
    if K == 1:
        return 1
        
    mu = _robust_soliton(K)
    
    r = rng.random()
    cumsum = 0.0
    for d in range(1, K + 1):
        cumsum += mu[d]
        if r <= cumsum:
            return d
            
    return K


class LTEncoder(IFountainEncoder):
    """LT encoder with Robust Soliton degree distribution and numpy XOR."""

    def encode(
        self,
        chunks: list[bytes],
        seed: int,
        overhead_ratio: float,
    ) -> list[EncodedPacket]:
        """
        Encode source chunks into LT-encoded packets.
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

        # Pre-convert chunks to numpy arrays for faster XORing
        chunk_arrays = [np.frombuffer(c, dtype=np.uint8) for c in chunks]

        # Generate encoded packets
        num_packets = int(K * (1.1 + overhead_ratio)) + 2
        encoded = []

        # Create RNG instance for this encoding session
        # Individual packet seeds derived from this
        session_rng = random.Random(seed)

        for packet_index in range(num_packets):
            # Deterministic packet seed
            packet_seed = session_rng.randint(0, 0xFFFFFFFF)
            packet_rng = random.Random(packet_seed)

            # Sample degree from Robust Soliton
            degree = _sample_degree(K, packet_rng)

            # Cap degree to ensure packet fits in UDP MTU (1500 bytes)
            # Degree 128 + 512B payload + metadata approx 1.1 KB
            degree = min(degree, 128)

            # Randomly select which chunks to XOR
            # We use packet_rng to ensure it's reproducible from the packet_seed
            chunk_ids = sorted(packet_rng.sample(range(K), min(degree, K)))

            # XOR selected chunks using numpy (vectorized)
            res_arr = np.zeros(chunk_size, dtype=np.uint8)
            for idx in chunk_ids:
                res_arr ^= chunk_arrays[idx]

            encoded.append(
                EncodedPacket(
                    packet_id=packet_index,
                    pass_id=0, # set by pipeline
                    seed=packet_seed,
                    degree=len(chunk_ids),
                    chunk_ids=chunk_ids,
                    data=res_arr.tobytes(),
                    source_chunk_count=K,
                )
            )

        return encoded
