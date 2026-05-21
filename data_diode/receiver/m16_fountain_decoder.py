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

    Converts pooled packets to format expected by LT decoder.
    """

    def __init__(self, codec: str = "lt"):
        """
        Initialize fountain decoder wrapper.

        Parameters:
            codec: Codec name ("lt" or "raptorq").
        """
        self.codec = codec
        self.decoder = get_decoder(codec)

    def decode_window(
        self,
        pooled_packets: List[PooledPacket],
        K: int,
        chunk_size: int
    ) -> DecodeResult:
        """
        Decode a window of pooled packets.

        Parameters:
            pooled_packets: List of PooledPacket from pool.
            K: Number of original chunks.
            chunk_size: Bytes per chunk.

        Returns:
            DecodeResult with chunks (may contain None for unsrecoverable).

        Raises:
            ValueError: if K or chunk_size invalid.
        """
        if K <= 0:
            raise ValueError(f"K must be positive, got {K}")

        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")

        if not pooled_packets:
            logger.warning("No packets to decode")
            return DecodeResult(chunks=[], missing_ids=list(range(K)), success=False)

        # Convert pooled packets to decoder format
        packets_for_decoder = []
        for p in pooled_packets:
            packets_for_decoder.append(EncodedPacket(
                degree=p.degree,
                seed=p.fountain_seed,
                data=p.payload
            ))

        # Call fountain decoder
        try:
            result = self.decoder.decode(packets_for_decoder, K)
            return result
        except Exception as e:
            logger.error(f"Fountain decoder error: {e}")
            # Return partial result (all None)
            missing = list(range(K))
            return DecodeResult(chunks=[None] * K, missing_ids=missing, success=False)

    def decode_multi_pass(
        self,
        pooled_packets_by_pass: Dict[int, List[PooledPacket]],
        K: int,
        chunk_size: int
    ) -> DecodeResult:
        """
        Decode using multiple passes (redundancy across passes).

        Parameters:
            pooled_packets_by_pass: Dict[pass_id] -> list of PooledPacket.
            K: Number of original chunks.
            chunk_size: Bytes per chunk.

        Returns:
            DecodeResult combining results from all passes.

        Note: First successful pass is returned. If all fail, returns
              partial results with available chunks.
        """
        if not pooled_packets_by_pass:
            logger.warning("No passes with packets")
            missing = list(range(K))
            return DecodeResult(chunks=[None] * K, missing_ids=missing, success=False)

        combined_chunks = [None] * K
        total_recovered = 0

        for pass_id in sorted(pooled_packets_by_pass.keys()):
            packets = pooled_packets_by_pass[pass_id]
            if not packets:
                continue

            result = self.decode_window(packets, K, chunk_size)

            # Update combined result
            for i, chunk in enumerate(result.chunks):
                if chunk is not None and combined_chunks[i] is None:
                    combined_chunks[i] = chunk
                    total_recovered += 1

            # Early exit if all chunks recovered
            if total_recovered == K:
                logger.info(f"Complete recovery from pass {pass_id}")
                missing_ids = [i for i, chunk in enumerate(combined_chunks) if chunk is None]
                return DecodeResult(chunks=combined_chunks, missing_ids=missing_ids, success=True)

        if total_recovered > 0:
            logger.info(f"Partial recovery: {total_recovered}/{K} chunks")

        missing_ids = [i for i, chunk in enumerate(combined_chunks) if chunk is None]
        return DecodeResult(
            chunks=combined_chunks,
            missing_ids=missing_ids,
            success=(total_recovered == K)
        )

    def get_recovery_stats(self, result: DecodeResult) -> Dict:
        """
        Extract recovery statistics from decode result.

        Parameters:
            result: DecodeResult from decode operation.

        Returns:
            Dict with stats.
        """
        chunks_recovered = sum(1 for c in result.chunks if c is not None)
        chunks_missing = sum(1 for c in result.chunks if c is None)

        return {
            "chunks_recovered": chunks_recovered,
            "chunks_missing": chunks_missing,
            "recovery_rate": chunks_recovered / len(result.chunks) if result.chunks else 0.0,
            "success": result.success,
            "missing_ids": result.missing_ids,
        }
