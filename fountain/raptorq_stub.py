"""
RaptorQ stub. Registered so 'raptorq' name resolves cleanly.
Replace this file's encode/decode bodies in Phase 4 — nothing else changes.
"""
from __future__ import annotations
from common.models import EncodedPacket, DecodeResult
from fountain.interface import IFountainEncoder, IFountainDecoder
from fountain.interface import register_encoder, register_decoder


class RaptorQEncoder(IFountainEncoder):
    def encode(self, chunks, seed, overhead_ratio):
        raise NotImplementedError("RaptorQ not yet implemented. Use 'lt'.")

class RaptorQDecoder(IFountainDecoder):
    def decode(self, packets, K_prime):
        raise NotImplementedError("RaptorQ not yet implemented. Use 'lt'.")

register_encoder("raptorq", RaptorQEncoder)
register_decoder("raptorq", RaptorQDecoder)
