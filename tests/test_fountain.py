"""Tests for fountain codecs (LT)."""
from __future__ import annotations
import pytest
import random
from fountain.interface import get_encoder, get_decoder
from tests.utils.loss_simulator import apply_random_loss


def test_lt_basic():
    encoder = get_encoder("lt")
    decoder = get_decoder("lt")
    
    # Small K
    chunks = [b"chunk_" + str(i).encode().ljust(10, b"x") for i in range(20)]
    seed = 42
    
    # Encode with 50% overhead
    packets = encoder.encode(chunks, seed, 0.5)
    assert len(packets) >= 20
    
    # Decode with all packets
    result = decoder.decode(packets, len(chunks))
    assert result.success
    assert result.recovered_count == 20
    assert b"".join([c for c in result.chunks if c is not None]) == b"".join(chunks)


def test_lt_with_loss():
    encoder = get_encoder("lt")
    decoder = get_decoder("lt")
    
    chunks = [random.randbytes(100) for _ in range(100)]
    seed = 123
    
    # Encode with 100% overhead
    packets = encoder.encode(chunks, seed, 1.0)
    
    # Apply 20% loss
    lost_packets = [p for p in apply_random_loss(packets, 0.2, seed=7) if p is not None]
    
    # Decode
    result = decoder.decode(lost_packets, len(chunks))
    assert result.success
    assert result.recovered_count == 100
    assert b"".join([c for c in result.chunks if c is not None]) == b"".join(chunks)


def test_empty_pool():
    decoder = get_decoder("lt")
    result = decoder.decode([], 10)
    assert not result.success
    assert result.recovered_count == 0
    assert all(c is None for c in result.chunks)
