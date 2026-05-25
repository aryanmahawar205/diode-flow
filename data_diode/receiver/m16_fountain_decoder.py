"""
Fountain decoder wrapper for receiver pipeline.
"""

from __future__ import annotations

import logging
from data_diode.fountain.interface import get_decoder, DecodeResult, EncodedPacket

logger = logging.getLogger(__name__)


class FountainDecoderWrapper:
    """
    Wrapper around fountain decoder for receiver pipeline.
    """

    def __init__(self, codec: str = "lt"):
        self.codec = codec
        self.decoder = get_decoder(codec)

    def decode_window(
        self,
        pooled_packets: list[EncodedPacket],
        K_prime: int,
        chunk_size: int,
    ) -> DecodeResult:
        """
        Decode unified pool (all passes combined) in ONE decode call.
        """
        if not pooled_packets:
            return DecodeResult(
                chunks=[None] * K_prime,
                success=False,
                recovered_count=0,
                missing_ids=list(range(K_prime)),
                packets_used=0,
            )

        # Unified decode — decoder handles multi-pass packets transparently
        try:
            return self.decoder.decode(pooled_packets, K_prime=K_prime)
        except Exception as e:
            logger.error(f"Fountain decoder error: {e}")
            return DecodeResult(
                chunks=[None] * K_prime,
                success=False,
                recovered_count=0,
                missing_ids=list(range(K_prime)),
                packets_used=len(pooled_packets),
            )
