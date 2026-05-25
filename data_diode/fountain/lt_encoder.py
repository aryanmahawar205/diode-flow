"""
LT (Luby Transform) encoder implementation.

This module implements an LT encoder using Robust Soliton Distribution for degree
selection and XOR operations to generate encoded packets.
"""

from __future__ import annotations

import logging
import random
import math
import numpy as np
from data_diode.fountain.interface import IFountainEncoder, EncodedPacket

logger = logging.getLogger(__name__)

def _robust_soliton(K: int, c: float = 0.03, delta: float = 0.02) -> list[float]:
    """
    Correct Robust Soliton Distribution.
    c=0.03, delta=0.02 are standard production parameters.
    """
    R     = c * math.log(K / delta) * math.sqrt(K)
    pivot = max(1, int(math.floor(K / R)))

    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))

    tau = [0.0] * (K + 1)
    for d in range(1, min(pivot, K + 1)):
        tau[d] = R / (d * K)
    if 1 <= pivot <= K:
        tau[pivot] = (R * math.log(R / delta)) / K

    mu_raw = [rho[d] + tau[d] for d in range(K + 1)]
    Z = sum(mu_raw[1:])
    return [0.0] + [v / Z for v in mu_raw[1:]]


def _build_cdf(pmf: list[float]) -> list[float]:
    cdf, running = [0.0] * len(pmf), 0.0
    for i, p in enumerate(pmf):
        running += p
        cdf[i] = running
    return cdf


def _sample_degree(cdf: list[float], rng: random.Random) -> int:
    u = rng.random()
    lo, hi = 1, len(cdf) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cdf[mid] < u: lo = mid + 1
        else:             hi = mid
    return lo


class LTEncoder(IFountainEncoder):
    """LT encoder implementation."""

    def encode(self, chunks: list[bytes], seed: int, overhead_ratio: float) -> list[EncodedPacket]:
        """
        Encode source chunks into LT-encoded packets.
        """
        if not chunks:
            raise ValueError("chunks list cannot be empty")
        
        K_prime    = len(chunks)
        chunk_size = len(chunks[0])
        n_packets  = math.ceil(K_prime * (1.0 + overhead_ratio))

        mu  = _robust_soliton(K_prime)
        cdf = _build_cdf(mu)
        rng = random.Random(seed)    # ← instance, not global state

        encoded = []
        for packet_id in range(n_packets):
            degree    = min(_sample_degree(cdf, rng), K_prime, 64) # Cap degree for Phase 2 MTU safety
            chunk_ids = sorted(rng.sample(range(K_prime), degree))
            
            # numpy XOR (performance)
            payload = np.zeros(chunk_size, dtype=np.uint8)
            for idx in chunk_ids:
                payload ^= np.frombuffer(chunks[idx], dtype=np.uint8)
            data = payload.tobytes()

            encoded.append(EncodedPacket(
                packet_id          = packet_id,
                pass_id            = 0,           # caller sets actual pass_id after
                seed               = seed,
                degree             = degree,
                chunk_ids          = chunk_ids,   # ← stored explicitly
                data               = data,
                source_chunk_count = K_prime,
            ))
        
        return encoded
