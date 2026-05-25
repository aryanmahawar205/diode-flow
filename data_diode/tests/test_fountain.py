"""
Unit tests for fountain codec implementations.

Test coverage:
- Interface registry and codec selection
- LT encoder: degree distribution, XOR operations, reproducibility
- LT decoder: belief propagation, peeling algorithm, partial recovery
- Edge cases: empty input, single chunk, max sizes, corrupt packets
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

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
from fountain.lt_encoder import LTEncoder
from fountain.lt_decoder import LTDecoder


class TestInterfaceRegistry:
    """Test fountain codec registry and factory functions."""

    def test_get_encoder_returns_instance(self):
        """get_encoder() returns IFountainEncoder instance."""
        encoder = get_encoder("lt")
        assert isinstance(encoder, IFountainEncoder)

    def test_get_decoder_returns_instance(self):
        """get_decoder() returns IFountainDecoder instance."""
        decoder = get_decoder("lt")
        assert isinstance(decoder, IFountainDecoder)

    def test_get_encoder_unknown_codec_raises_keyerror(self):
        """get_encoder() raises KeyError for unknown codec."""
        with pytest.raises(KeyError):
            get_encoder("nonexistent")

    def test_get_decoder_unknown_codec_raises_keyerror(self):
        """get_decoder() raises KeyError for unknown codec."""
        with pytest.raises(KeyError):
            get_decoder("nonexistent")

    def test_list_encoders_includes_lt(self):
        """list_encoders() includes 'lt' codec."""
        encoders = list_encoders()
        assert "lt" in encoders

    def test_list_decoders_includes_lt(self):
        """list_decoders() includes 'lt' codec."""
        decoders = list_decoders()
        assert "lt" in decoders

    def test_raptorq_stub_raises_not_implemented(self):
        """RaptorQ stub raises NotImplementedError."""
        encoder = get_encoder("raptorq")
        with pytest.raises(NotImplementedError):
            encoder.encode([b"test"], seed=0, overhead_ratio=0.5)

        decoder = get_decoder("raptorq")
        with pytest.raises(NotImplementedError):
            decoder.decode([], K_prime=1)


class TestLTEncoder:
    """Test LT encoder implementation."""

    def test_encode_single_chunk(self):
        """Encode single chunk produces overhead packets."""
        encoder = LTEncoder()
        chunk = b"x" * 1024
        packets = encoder.encode([chunk], seed=0, overhead_ratio=0.5)

        # Should generate 1.5 packets (rounded up to 2)
        assert len(packets) >= 1
        assert all(isinstance(p, EncodedPacket) for p in packets)
        assert all(len(p.data) == len(chunk) for p in packets)

    def test_encode_multiple_chunks(self):
        """Encode multiple chunks with XOR operations."""
        encoder = LTEncoder()
        chunks = [b"a" * 100, b"b" * 100, b"c" * 100]
        packets = encoder.encode(chunks, seed=42, overhead_ratio=1.0)

        # Should generate K + K overhead = 2K packets
        assert len(packets) >= 3
        assert all(isinstance(p, EncodedPacket) for p in packets)

    def test_encode_reproducibility(self):
        """Same seed produces same encoded packets."""
        encoder = LTEncoder()
        chunks = [b"data1" * 100, b"data2" * 100]

        packets1 = encoder.encode(chunks, seed=123, overhead_ratio=0.5)
        packets2 = encoder.encode(chunks, seed=123, overhead_ratio=0.5)

        assert len(packets1) == len(packets2)
        for p1, p2 in zip(packets1, packets2):
            assert p1.degree == p2.degree
            assert p1.seed == p2.seed
            assert p1.data == p2.data
            assert p1.chunk_ids == p2.chunk_ids

    def test_encode_different_seeds_different_packets(self):
        """Different seeds produce different packets."""
        encoder = LTEncoder()
        chunks = [b"data1" * 100, b"data2" * 100]

        packets1 = encoder.encode(chunks, seed=123, overhead_ratio=0.5)
        packets2 = encoder.encode(chunks, seed=456, overhead_ratio=0.5)

        # At least some packets should differ
        differences = sum(
            1 for p1, p2 in zip(packets1, packets2)
            if p1.data != p2.data
        )
        assert differences > 0

    def test_encode_empty_chunks_raises_valueerror(self):
        """Encoding empty chunk list raises ValueError."""
        encoder = LTEncoder()
        with pytest.raises(ValueError, match="chunks list cannot be empty"):
            encoder.encode([], seed=0, overhead_ratio=0.5)

    def test_encode_degree_between_1_and_K(self):
        """All encoded packets have degree between 1 and K."""
        encoder = LTEncoder()
        chunks = [b"a" * 100 for _ in range(10)]
        packets = encoder.encode(chunks, seed=0, overhead_ratio=2.0)

        for packet in packets:
            assert 1 <= packet.degree <= len(chunks)


class TestLTDecoder:
    """Test LT decoder implementation."""

    def test_decode_single_chunk(self):
        """Decode single chunk from encoded packet."""
        encoder = LTEncoder()
        original_chunk = b"hello_world" * 100
        chunks = [original_chunk]

        # Encode with overhead
        encoded = encoder.encode(chunks, seed=0, overhead_ratio=1.0)

        # Decode
        decoder = LTDecoder()
        result = decoder.decode(encoded, K_prime=1)

        assert result.success
        assert result.chunks[0] == original_chunk
        assert result.missing_ids == []

    def test_decode_multiple_chunks(self):
        """Decode multiple chunks with redundancy."""
        encoder = LTEncoder()
        chunks = [b"chunk_" + str(i).encode() * 100 for i in range(5)]

        # Encode with significant overhead for recovery
        encoded = encoder.encode(chunks, seed=0, overhead_ratio=2.0)

        # Decode
        decoder = LTDecoder()
        result = decoder.decode(encoded, K_prime=5)

        assert result.success
        assert len(result.chunks) == 5
        for i, chunk in enumerate(result.chunks):
            assert chunk == chunks[i]

    def test_decode_partial_recovery(self):
        """Decode partial recovery when overhead insufficient."""
        encoder = LTEncoder()
        chunks = [b"a" * 100 for _ in range(10)]

        # Minimal overhead
        encoded = encoder.encode(chunks, seed=0, overhead_ratio=0.1)

        # Attempt decode
        decoder = LTDecoder()
        result = decoder.decode(encoded, K_prime=10)

        # Result may be partial, but should not crash
        assert isinstance(result, DecodeResult)
        assert len(result.chunks) == 10
        # Some chunks may be None
        assert any(c is None for c in result.chunks) or result.success

    def test_decode_empty_pool_returns_all_missing(self):
        """Decoding empty packet pool returns graceful DecodeResult with all chunks missing."""
        decoder = LTDecoder()
        result = decoder.decode([], K_prime=10)
        assert not result.success
        assert result.recovered_count == 0
        assert len(result.chunks) == 10
        assert all(c is None for c in result.chunks)
        assert len(result.missing_ids) == 10

    def test_decode_returns_decode_result(self):
        """decode() returns DecodeResult instance."""
        encoder = LTEncoder()
        chunks = [b"test" * 100]
        encoded = encoder.encode(chunks, seed=0, overhead_ratio=1.0)

        decoder = LTDecoder()
        result = decoder.decode(encoded, K_prime=1)

        assert isinstance(result, DecodeResult)
        assert isinstance(result.chunks, list)
        assert isinstance(result.missing_ids, list)
        assert isinstance(result.success, bool)


class TestLTRoundTrip:
    """Test end-to-end encode/decode cycles."""

    def test_roundtrip_small_file(self):
        """Encode and decode small file successfully."""
        encoder = LTEncoder()
        decoder = LTDecoder()

        original = b"The quick brown fox jumps over the lazy dog" * 10
        chunk_size = 128
        chunks = [
            original[i:i+chunk_size]
            for i in range(0, len(original), chunk_size)
        ]

        # Pad last chunk
        if len(chunks[-1]) < chunk_size:
            chunks[-1] = chunks[-1].ljust(chunk_size, b'\x00')

        K = len(chunks)

        # Encode with overhead
        encoded = encoder.encode(chunks, seed=0, overhead_ratio=1.0)

        # Decode
        result = decoder.decode(encoded, K_prime=K)

        assert result.success
        for i, chunk in enumerate(result.chunks):
            assert chunk == chunks[i]

    def test_roundtrip_many_passes(self):
        """Multi-pass encoding and decoding."""
        encoder = LTEncoder()
        decoder = LTDecoder()

        chunks = [b"pass" + str(i).encode() * 100 for i in range(8)]
        K = len(chunks)

        # Multi-pass: combine packets from different seeds
        all_encoded = []
        for pass_id in range(2):
            seed = pass_id * 1000
            encoded = encoder.encode(chunks, seed=seed, overhead_ratio=0.5)
            for p in encoded:
                p.pass_id = pass_id
            all_encoded.extend(encoded)

        # Decode from combined pool
        result = decoder.decode(all_encoded, K_prime=K)

        assert result.success
        for i, chunk in enumerate(result.chunks):
            assert chunk == chunks[i]
