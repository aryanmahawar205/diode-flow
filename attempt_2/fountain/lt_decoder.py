"""
LT decoder using belief propagation (peeling algorithm).
Reads chunk_ids directly from EncodedPacket — never re-derives.
numpy XOR in hot path. set operations for O(1) edge removal.
Returns graceful DecodeResult on empty pool — never raises.
"""
from __future__ import annotations
import logging
import numpy as np
from common.models import EncodedPacket, DecodeResult
from fountain.interface import IFountainDecoder, register_decoder

logger = logging.getLogger(__name__)


class LTDecoder(IFountainDecoder):

    def decode(self, packets: list[EncodedPacket], K_prime: int) -> DecodeResult:
        if K_prime <= 0:
            raise ValueError(f"K_prime must be positive, got {K_prime}")

        # Graceful empty pool — never raise
        if not packets:
            return DecodeResult(chunks=[None]*K_prime, success=False,
                                recovered_count=0,
                                missing_ids=list(range(K_prime)),
                                packets_used=0)

        # DoS guard: degree cap
        safe = [p for p in packets if 1 <= p.degree <= K_prime]
        if not safe:
            return DecodeResult(chunks=[None]*K_prime, success=False,
                                recovered_count=0,
                                missing_ids=list(range(K_prime)),
                                packets_used=0)

        chunk_size = len(safe[0].data)

        # Build Tanner graph
        recovered        = [None] * K_prime          # bytes | None per chunk
        pkt_payload      = []                         # bytearray per packet
        pkt_chunks       = []                         # set[int] per packet
        chunk_to_pkts    = [set() for _ in range(K_prime)]

        for pi, pkt in enumerate(safe):
            valid = [c for c in pkt.chunk_ids if 0 <= c < K_prime]
            if len(valid) != pkt.degree:
                continue   # malformed — skip
            pkt_payload.append(bytearray(pkt.data))
            pkt_chunks.append(set(valid))
            cur_pi = len(pkt_payload) - 1
            for cid in valid:
                chunk_to_pkts[cid].add(cur_pi)

        # Peeling decoder
        ripple = [pi for pi, cs in enumerate(pkt_chunks) if len(cs) == 1]

        while ripple:
            pi = ripple.pop()
            if len(pkt_chunks[pi]) != 1:
                continue

            cid = next(iter(pkt_chunks[pi]))
            if recovered[cid] is not None:
                pkt_chunks[pi].clear()
                continue

            recovered[cid] = bytes(pkt_payload[pi])
            pkt_chunks[pi].clear()

            for other_pi in list(chunk_to_pkts[cid]):
                if other_pi == pi:
                    continue
                if cid not in pkt_chunks[other_pi]:
                    continue

                # FIX A: Fast numpy XOR in the peeling loop
                r = np.frombuffer(pkt_payload[other_pi], dtype=np.uint8).copy()
                k = np.frombuffer(recovered[cid], dtype=np.uint8)
                r ^= k
                pkt_payload[other_pi] = bytearray(r.tobytes())

                pkt_chunks[other_pi].discard(cid)   # O(1) set removal

                if len(pkt_chunks[other_pi]) == 1:
                    ripple.append(other_pi)

            chunk_to_pkts[cid].clear()

        missing = [i for i, c in enumerate(recovered) if c is None]
        success = len(missing) == 0

        logger.debug(f"Decoded {K_prime - len(missing)}/{K_prime} chunks "
                     f"from {len(safe)} packets")

        return DecodeResult(
            chunks          = recovered,
            success         = success,
            recovered_count = K_prime - len(missing),
            missing_ids     = missing,
            packets_used    = len(safe),
        )


register_decoder("lt", LTDecoder)
