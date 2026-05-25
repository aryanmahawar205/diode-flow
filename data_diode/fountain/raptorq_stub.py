"""
RaptorQ encoder/decoder stub.

This module provides placeholder RaptorQ implementations (raising NotImplementedError).
It exists to satisfy the codec registry and allows the pipeline to reference RaptorQ
as a future option without breaking the system.

Why a stub?
- RaptorQ is more complex than LT and requires careful RFC 6330 implementation.
- The stub allows Phase 1 testing with LT while reserving the RaptorQ namespace.
- Satisfies the invariant: "fountain interface is the only way to access codecs."

Future work:
- Replace with real RaptorQ encoder/decoder (Phase 4 optimization).
- No other code changes needed — register_encoder/register_decoder handle swap.
"""

from __future__ import annotations

import logging

from data_diode.fountain.interface import IFountainEncoder, IFountainDecoder, EncodedPacket, DecodeResult

logger = logging.getLogger(__name__)


class RaptorQEncoder(IFountainEncoder):
    """RaptorQ encoder stub (not yet implemented)."""

    def encode(
        self,
        chunks: list[bytes],
        seed: int,
        overhead_ratio: float,
    ) -> list[EncodedPacket]:
        """
        RaptorQ encode (stub).

        Raises:
            NotImplementedError: Phase 4 optimization, not yet implemented.
        """
        raise NotImplementedError(
            "RaptorQ encoder not yet implemented. Use 'lt' codec for Phase 1-3."
        )


class RaptorQDecoder(IFountainDecoder):
    """RaptorQ decoder stub (not yet implemented)."""

    def decode(
        self,
        pool: list[EncodedPacket],
        K_prime: int,
    ) -> DecodeResult:
        """
        RaptorQ decode (stub).

        Raises:
            NotImplementedError: Phase 4 optimization, not yet implemented.
        """
        raise NotImplementedError(
            "RaptorQ decoder not yet implemented. Use 'lt' codec for Phase 1-3."
        )
