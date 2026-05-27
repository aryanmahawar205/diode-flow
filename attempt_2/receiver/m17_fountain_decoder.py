"""
Fountain decoder wrapper.
CRITICAL: always passes UNIFIED pool to decoder — never decodes passes separately.
Cross-pass recovery only works when all packets are in ONE Tanner graph.
"""
from __future__ import annotations
import logging
from common.models import EncodedPacket, DecodeResult
from common.config import MAX_DEGREE
from fountain.interface import get_decoder

logger = logging.getLogger(__name__)


class FountainDecoder:
    def __init__(self, codec: str = "lt", max_degree: int = MAX_DEGREE):
        self._decoder    = get_decoder(codec)
        self._max_degree = max_degree

    def decode(self, pool: list[EncodedPacket], K_prime: int,
               chunk_size: int) -> DecodeResult:
        """
        Decode unified pool. Never split by pass_id before calling.
        All passes → one graph → cross-pass recovery works.
        """
        if not pool:
            from common.models import DecodeResult
            return DecodeResult(chunks=[None]*K_prime, success=False,
                                recovered_count=0, missing_ids=list(range(K_prime)),
                                packets_used=0)

        result = self._decoder.decode(pool, K_prime=K_prime,
                                       max_degree=self._max_degree)
        logger.info(f"Fountain decoded {result.recovered_count}/{K_prime} chunks "
                    f"from {result.packets_used} packets")
        return result
