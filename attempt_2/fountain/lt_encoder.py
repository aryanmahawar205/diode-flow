"""
LT (Luby Transform) fountain encoder.
Uses Robust Soliton Distribution for degree selection.
Uses numpy XOR for performance — never byte-by-byte loops.
Uses random.Random instances — never global random.seed().
"""
from __future__ import annotations
import math
import random
import logging
import numpy as np
from common.models import EncodedPacket
from common.config import MAX_DEGREE
from fountain.interface import IFountainEncoder, register_encoder

logger = logging.getLogger(__name__)


def _robust_soliton_cdf(K: int, c: float = 0.03, delta: float = 0.02) -> list[float]:
    """
    Correct Robust Soliton Distribution CDF.
    Standard formula: R = c * ln(K/delta) * sqrt(K)
    Spike at d=1..pivot, extra mass at d=pivot.
    """
    R     = c * math.log(K / delta) * math.sqrt(K)
    pivot = min(K, max(1, int(math.floor(K / R))))

    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))

    tau = [0.0] * (K + 1)
    for d in range(1, pivot):
        tau[d] = R / (d * K)
    if 1 <= pivot <= K:
        tau[pivot] = (R * math.log(R / delta)) / K

    total = sum(rho[d] + tau[d] for d in range(1, K + 1))
    cdf   = [0.0] * (K + 2)
    for d in range(1, K + 1):
        cdf[d] = cdf[d - 1] + (rho[d] + tau[d]) / total
    cdf[K] = 1.0
    return cdf


def _sample_degree(cdf: list[float], rng: random.Random) -> int:
    u, lo, hi = rng.random(), 1, len(cdf) - 2
    while lo < hi:
        mid = (lo + hi) // 2
        if cdf[mid] < u: lo = mid + 1
        else:            hi = mid
    return lo


class LTEncoder(IFountainEncoder):
    """LT encoder. numpy XOR. random.Random instances. chunk_ids stored."""

    def __init__(self, c: float = 0.03, delta: float = 0.02):
        self._c, self._delta = c, delta

    def encode(self, chunks: list[bytes], seed: int,
               overhead_ratio: float) -> list[EncodedPacket]:
        if not chunks:
            raise ValueError("chunks list cannot be empty")
        if any(len(c) != len(chunks[0]) for c in chunks):
            raise ValueError("All chunks must be equal length")

        K_prime    = len(chunks)
        chunk_size = len(chunks[0])
        # Add a constant 32 extra packets to the overhead to handle small (tail) windows/files
        n_packets  = math.ceil(K_prime * (1.0 + overhead_ratio)) + 32

        # FIX A: numpy XOR - Pre-convert chunks to numpy arrays BEFORE the packet generation loop
        # Do this once per encode() call, not per packet:
        np_chunks = [np.frombuffer(c, dtype=np.uint8) for c in chunks]

        cdf = _robust_soliton_cdf(K_prime, self._c, self._delta)
        # FIX C: random.Random Instance (Not Global State)
        # Create ONCE per encode() call, before the packet loop:
        rng = random.Random(seed)

        packets = []
        for pid in range(n_packets):
            degree    = min(_sample_degree(cdf, rng), K_prime, MAX_DEGREE)
            chunk_ids = sorted(rng.sample(range(K_prime), degree))

            # FIX A: Then inside the packet loop:
            payload = np_chunks[chunk_ids[0]].copy()
            for idx in chunk_ids[1:]:
                payload ^= np_chunks[idx]
            data = payload.tobytes()

            packets.append(EncodedPacket(
                packet_id          = pid,
                pass_id            = 0,          # pipeline sets actual pass_id
                seed               = seed,
                degree             = degree,
                chunk_ids          = chunk_ids,  # FIX B: store chunk_ids
                data               = data,
                source_chunk_count = K_prime,
            ))

        logger.debug(f"Encoded K'={K_prime} chunks → {len(packets)} packets")
        return packets


register_encoder("lt", LTEncoder)
