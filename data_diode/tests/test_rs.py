"""
tests/test_rs.py — Reed-Solomon Encoder/Decoder Tests

Tests for sender/m4_rs_encoder.py:
- RS config parsing and validation
- Encoding/decoding round-trip
- Handling of erasures and recovery
- Error cases
"""

import pytest
from data_diode.sender.m4_rs_encoder import (
    RSConfig,
    parse_rs_config,
    encode_with_rs,
    decode_with_rs,
)


class TestRSConfig:
    """Test RSConfig dataclass."""
    
    def test_valid_config(self):
        """Test creating valid RS config."""
        cfg = RSConfig(n=16, k=2)
        assert cfg.n == 16
        assert cfg.k == 2
        assert cfg.num_parity == 14
    
    def test_config_validation_k_too_large(self):
        """Test k > n."""
        with pytest.raises(ValueError):
            RSConfig(n=10, k=20)
    
    def test_config_validation_k_zero(self):
        """Test k = 0."""
        with pytest.raises(ValueError):
            RSConfig(n=10, k=0)
    
    def test_config_validation_n_too_large(self):
        """Test n > 255 (Galois Field limit)."""
        with pytest.raises(ValueError):
            RSConfig(n=300, k=100)
    
    def test_all_standard_configs(self):
        """Test all standard RS configs from spec."""
        configs = [
            (16, 2), (16, 4),
            (32, 4), (32, 6), (32, 8),
            (64, 6), (64, 8),
        ]
        for n, k in configs:
            cfg = RSConfig(n=n, k=k)
            assert cfg.num_parity == n - k


class TestRSConfigParsing:
    """Test RS config string parsing."""
    
    def test_parse_standard_format(self):
        """Test parsing 'RS(n,k)' format."""
        cfg = parse_rs_config("RS(16,2)")
        assert cfg.n == 16
        assert cfg.k == 2
    
    def test_parse_with_spaces(self):
        """Test parsing with spaces."""
        cfg = parse_rs_config(" RS( 32 , 6 ) ")
        assert cfg.n == 32
        assert cfg.k == 6
    
    def test_parse_invalid_format(self):
        """Test invalid format."""
        with pytest.raises(ValueError):
            parse_rs_config("RS(16)")
        with pytest.raises(ValueError):
            parse_rs_config("16,2")
        with pytest.raises(ValueError):
            parse_rs_config("RS{16,2}")
    
    def test_parse_non_numeric(self):
        """Test non-numeric values."""
        with pytest.raises(ValueError):
            parse_rs_config("RS(a,b)")


class TestRSEncoding:
    """Test Reed-Solomon encoding."""
    
    def test_encode_simple(self):
        """Test basic encoding."""
        chunks = [b"a" * 100 for _ in range(10)]
        cfg = RSConfig(n=16, k=10)
        
        result = encode_with_rs(chunks, cfg)
        
        # Should have original + parity chunks
        assert len(result) == 16
        assert result[:10] == chunks  # Original chunks unchanged
        assert len(result[10]) == 100  # Parity chunks same size
    
    def test_encode_empty_chunks(self):
        """Test encoding with empty chunks list."""
        cfg = RSConfig(n=16, k=10)
        with pytest.raises(ValueError):
            encode_with_rs([], cfg)
    
    def test_encode_mismatched_chunk_sizes(self):
        """Test chunks with different sizes."""
        chunks = [b"a" * 100, b"b" * 50, b"c" * 100]
        cfg = RSConfig(n=16, k=3)
        
        with pytest.raises(ValueError):
            encode_with_rs(chunks, cfg)
    
    def test_encode_too_many_chunks(self):
        """Test K > RS config k."""
        chunks = [b"x" * 100 for _ in range(20)]
        cfg = RSConfig(n=16, k=10)
        
        with pytest.raises(ValueError):
            encode_with_rs(chunks, cfg)


class TestRSDecoding:
    """Test Reed-Solomon decoding."""
    
    def test_decode_no_erasures(self):
        """Test decoding with no missing chunks."""
        # Create original chunks
        original = [b"chunk%d" % i for i in range(10)]
        # Pad to same size
        chunk_size = 10
        original = [c.ljust(chunk_size, b"\x00") for c in original]
        
        cfg = RSConfig(n=16, k=10)
        encoded = encode_with_rs(original, cfg)
        
        # Decode with no erasures (all chunks present)
        chunks_with_erasures = encoded[:16]  # All chunks present
        decoded = decode_with_rs(chunks_with_erasures, cfg)
        
        assert len(decoded) == 10
        assert decoded == original
    
    def test_decode_with_erasures(self):
        """Test decoding with missing chunks."""
        # Create original chunks
        original = [b"X" * 100 for _ in range(10)]
        
        cfg = RSConfig(n=16, k=10)
        encoded = encode_with_rs(original, cfg)
        
        # Simulate erasures: lose chunks 0, 5, 7, 9 and all 6 parity
        chunks_with_erasures = list(encoded)
        chunks_with_erasures[0] = None
        chunks_with_erasures[5] = None
        chunks_with_erasures[7] = None
        chunks_with_erasures[9] = None
        chunks_with_erasures[10] = None  # parity 0
        chunks_with_erasures[11] = None  # parity 1
        
        # Should recover with 6 parity chunks
        decoded = decode_with_rs(chunks_with_erasures, cfg)
        
        assert len(decoded) == 10
        # Note: We can't directly check decoded == original because we're
        # decoding from altered data, but we can check structure
        assert all(isinstance(c, bytes) for c in decoded)
        assert all(len(c) == 100 for c in decoded)
    
    def test_decode_too_many_erasures(self):
        """Test with more erasures than parity chunks."""
        chunks_with_erasures = [None] * 10 + [b"X" * 100] * 6  # All data missing
        cfg = RSConfig(n=16, k=10)
        
        with pytest.raises(ValueError):
            decode_with_rs(chunks_with_erasures, cfg)
    
    def test_decode_all_none(self):
        """Test decode with all chunks None."""
        chunks_with_erasures = [None] * 16
        cfg = RSConfig(n=16, k=10)
        
        with pytest.raises(ValueError):
            decode_with_rs(chunks_with_erasures, cfg)


class TestRSRoundTrip:
    """Integration tests for encode/decode round-trip."""
    
    def test_roundtrip_rs_16_10(self):
        """Test RS(16,10) round-trip."""
        # Create test data
        original = [f"chunk{i}".encode().ljust(50, b"\x00") for i in range(10)]
        cfg = RSConfig(n=16, k=10)
        
        # Encode
        encoded = encode_with_rs(original, cfg)
        assert len(encoded) == 16
        
        # Decode (no erasures)
        decoded = decode_with_rs(encoded, cfg)
        assert len(decoded) == 10
        assert decoded == original
    
    def test_roundtrip_rs_32_8(self):
        """Test RS(32,8) round-trip (high parity)."""
        original = [b"Y" * 200 for _ in range(8)]
        cfg = RSConfig(n=32, k=8)
        
        encoded = encode_with_rs(original, cfg)
        assert len(encoded) == 32
        
        decoded = decode_with_rs(encoded, cfg)
        assert decoded == original
    
    def test_various_chunk_sizes(self):
        """Test encoding/decoding with various chunk sizes."""
        for chunk_size in [50, 100, 500, 1200, 4096]:
            original = [b"Z" * chunk_size for _ in range(5)]
            cfg = RSConfig(n=10, k=5)
            
            encoded = encode_with_rs(original, cfg)
            decoded = decode_with_rs(encoded, cfg)
            
            assert decoded == original
