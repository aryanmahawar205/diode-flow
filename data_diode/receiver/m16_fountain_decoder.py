"""
Fountain decoder wrapper for receiver pipeline.

Step 16 of Phase 1: receiver/m16_fountain_decoder.py

Wraps the LT decoder to work with pooled packets from the receiver.
Decodes packets into chunks, handles partial success (pass to RS decoder).

Design:
- Takes pooled packets, extracts chunks
- Interfaces with LT decoder from fountain module
- Returns DecodeResult (chunks + recovery stats)
- Handles failures gracefully (partial results)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from data_diode.fountain import get_decoder, DecodeResult, EncodedPacket
from data_diode.receiver.m15_pooler import PooledPacket

logger = logging.getLogger(__name__)


class FountainDecoderWrapper:
    """
    Wrapper around fountain decoder for receiver pipeline.
    """

    def __init__(self, codec: str = "lt"):
        """
        Initialize fountain decoder wrapper.
        """
        self.codec = codec

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
        # because each packet carries its own chunk_ids regardless of pass
        decoder = get_decoder(self.codec)
        try:
            return decoder.decode(pooled_packets, K=K_prime)
        except Exception as e:
            logger.error(f"Fountain decoder error: {e}")
            return DecodeResult(
                chunks=[None] * K_prime,
                success=False,
                recovered_count=0,
                missing_ids=list(range(K_prime)),
                packets_used=len(pooled_packets),
            )

    def get_recovery_stats(self, result: DecodeResult) -> Dict:
        """
        Extract recovery statistics from decode result.
        """
        return {
            "chunks_recovered": result.recovered_count,
            "chunks_missing": len(result.missing_ids),
            "recovery_rate": result.recovered_count / len(result.chunks) if result.chunks else 0.0,
            "success": result.success,
            "missing_ids": result.missing_ids,
            "packets_used": result.packets_used,
        }
