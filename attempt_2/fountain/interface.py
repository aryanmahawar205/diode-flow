"""
Abstract interfaces for fountain codecs.
This is the ONLY way the pipeline accesses fountain coding.
LT or RaptorQ — the pipeline never knows which one is running.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from common.models import EncodedPacket, DecodeResult
import logging

logger = logging.getLogger(__name__)

_ENCODERS: dict[str, type] = {}
_DECODERS: dict[str, type] = {}


class IFountainEncoder(ABC):
    @abstractmethod
    def encode(self, chunks: list[bytes], seed: int,
               overhead_ratio: float) -> list[EncodedPacket]: ...

class IFountainDecoder(ABC):
    @abstractmethod
    def decode(self, packets: list[EncodedPacket], K_prime: int) -> DecodeResult: ...

def register_encoder(name: str, cls: type) -> None:
    if name in _ENCODERS:
        raise ValueError(f"Encoder '{name}' already registered")
    _ENCODERS[name] = cls

def register_decoder(name: str, cls: type) -> None:
    if name in _DECODERS:
        raise ValueError(f"Decoder '{name}' already registered")
    _DECODERS[name] = cls

def get_encoder(name: str = "lt") -> IFountainEncoder:
    if name not in _ENCODERS:
        raise KeyError(f"Encoder '{name}' not found. Available: {list(_ENCODERS)}")
    return _ENCODERS[name]()

def get_decoder(name: str = "lt") -> IFountainDecoder:
    if name not in _DECODERS:
        raise KeyError(f"Decoder '{name}' not found. Available: {list(_DECODERS)}")
    return _DECODERS[name]()

def list_encoders() -> list[str]: return list(_ENCODERS.keys())
def list_decoders() -> list[str]: return list(_DECODERS.keys())
