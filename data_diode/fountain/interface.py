"""
Fountain codec interface and registry.

This module defines the abstract base classes IFountainEncoder and IFountainDecoder,
and provides a codec registry system for selecting implementations (LT, RaptorQ, etc).

Why a separate interface?
- Allows multiple codec implementations (LT, RaptorQ) without changing pipeline code.
- Codecs are completely standalone — they don't import sender or receiver modules.
- The pipeline only interacts with codecs via this interface.
- New codecs are registered once in __init__.py and automatically available via get_encoder/get_decoder.

Key design decisions:
- Registry is global but immutable after initialization.
- Factory functions raise KeyError if codec not found (fail fast).
- Both encoder and decoder signatures match fountain code standards:
  * encode(chunks, seed, overhead_ratio) -> list[EncodedPacket]
  * decode(pool, K_prime) -> DecodeResult
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EncodedPacket:
    """One fountain-encoded packet."""
    packet_id: int          # unique within pass — for deduplication
    pass_id: int            # which transmission pass (0, 1)
    seed: int               # PRNG seed for this pass
    degree: int             # number of source chunks XOR'd
    chunk_ids: list[int]    # WHICH chunks were XOR'd — decoder reads directly
    data: bytes             # XOR'd payload
    source_chunk_count: int # K' = K + RS parity chunks
    transfer_id: str = ""   # routing metadata
    window_id: int = 0      # routing metadata


@dataclass
class DecodeResult:
    """Result of fountain decode."""
    chunks: list[bytes | None]   # None = not recovered
    success: bool
    recovered_count: int
    missing_ids: list[int]
    packets_used: int


class IFountainEncoder(ABC):
    """Abstract base class for fountain encoders."""

    @abstractmethod
    def encode(
        self,
        chunks: list[bytes],
        seed: int,
        overhead_ratio: float
    ) -> list[EncodedPacket]:
        """
        Encode source chunks using fountain code.

        Parameters:
            chunks: list[bytes] of K source chunks (all equal size).
            seed: PRNG seed for reproducible degree selection.
            overhead_ratio: fraction of K to generate as overhead packets.
                           e.g. overhead_ratio=0.5 for K chunks → 1.5*K encoded packets.

        Returns:
            list[EncodedPacket] with degree, seed, and data fields populated.

        Raises:
            ValueError: if chunks is empty, seed < 0, or overhead_ratio < 0.
        """
        pass


class IFountainDecoder(ABC):
    """Abstract base class for fountain decoders."""

    @abstractmethod
    def decode(
        self,
        pool: list[EncodedPacket],
        K: int
    ) -> DecodeResult:
        """
        Decode source chunks from encoded packet pool.

        Parameters:
            pool: list[EncodedPacket] collected from network or multi-pass.
            K: Number of source chunks to recover.

        Returns:
            DecodeResult with chunks and missing_ids populated.

        Raises:
            ValueError: if pool is empty or K <= 0.
        """
        pass


# Global codec registry
_encoder_registry: dict[str, type[IFountainEncoder]] = {}
_decoder_registry: dict[str, type[IFountainDecoder]] = {}


def register_encoder(name: str, encoder_class: type[IFountainEncoder]) -> None:
    """
    Register a fountain encoder implementation.

    Parameters:
        name: Codec name (e.g., "lt", "raptorq").
        encoder_class: Class implementing IFountainEncoder.

    Raises:
        ValueError: if name already registered.
    """
    if name in _encoder_registry:
        raise ValueError(f"Encoder '{name}' already registered")
    _encoder_registry[name] = encoder_class
    logger.debug(f"Registered encoder: {name}")


def register_decoder(name: str, decoder_class: type[IFountainDecoder]) -> None:
    """
    Register a fountain decoder implementation.

    Parameters:
        name: Codec name (e.g., "lt", "raptorq").
        decoder_class: Class implementing IFountainDecoder.

    Raises:
        ValueError: if name already registered.
    """
    if name in _decoder_registry:
        raise ValueError(f"Decoder '{name}' already registered")
    _decoder_registry[name] = decoder_class
    logger.debug(f"Registered decoder: {name}")


def get_encoder(name: str) -> IFountainEncoder:
    """
    Get a fountain encoder instance by name.

    Parameters:
        name: Codec name (e.g., "lt", "raptorq").

    Returns:
        IFountainEncoder instance.

    Raises:
        KeyError: if codec not registered.
    """
    if name not in _encoder_registry:
        raise KeyError(
            f"Encoder '{name}' not found. Registered: {list(_encoder_registry.keys())}"
        )
    return _encoder_registry[name]()


def get_decoder(name: str) -> IFountainDecoder:
    """
    Get a fountain decoder instance by name.

    Parameters:
        name: Codec name (e.g., "lt", "raptorq").

    Returns:
        IFountainDecoder instance.

    Raises:
        KeyError: if codec not registered.
    """
    if name not in _decoder_registry:
        raise KeyError(
            f"Decoder '{name}' not found. Registered: {list(_decoder_registry.keys())}"
        )
    return _decoder_registry[name]()


def list_encoders() -> list[str]:
    """Return list of registered encoder names."""
    return list(_encoder_registry.keys())


def list_decoders() -> list[str]:
    """Return list of registered decoder names."""
    return list(_decoder_registry.keys())
