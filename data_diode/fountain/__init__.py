"""
Fountain coding implementations and interface.

This module provides fountain code encoders and decoders for reliable packet
transmission over unreliable channels (UDP).

Available codecs are auto-registered when this module is imported.
"""

from __future__ import annotations

# Import interface first
from fountain.interface import (
    IFountainEncoder,
    IFountainDecoder,
    EncodedPacket,
    DecodeResult,
    register_encoder,
    register_decoder,
    get_encoder,
    get_decoder,
    list_encoders,
    list_decoders,
)

# Register concrete implementations
from fountain.lt_encoder import LTEncoder
from fountain.lt_decoder import LTDecoder
from fountain.raptorq_stub import RaptorQEncoder, RaptorQDecoder

register_encoder("lt", LTEncoder)
register_decoder("lt", LTDecoder)
register_encoder("raptorq", RaptorQEncoder)
register_decoder("raptorq", RaptorQDecoder)

__all__ = [
    "IFountainEncoder",
    "IFountainDecoder",
    "EncodedPacket",
    "DecodeResult",
    "register_encoder",
    "register_decoder",
    "get_encoder",
    "get_decoder",
    "list_encoders",
    "list_decoders",
]
