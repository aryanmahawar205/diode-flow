"""
tests/test_multipass.py — Multi-Pass Seed Generator Tests

Tests for sender/m7_multipass.py:
- Seed generation and determinism
- Seed uncorrelation (different passes → different seeds)
- Hamming distance verification
"""

import pytest
from sender.m7_multipass import (
    seed_for_pass,
    generate_seeds,
    verify_seed_uncorrelation,
)


class TestSeedGeneration:
    """Test seed generation."""
    
    def test_seed_determinism(self):
        """Test same parameters → same seed."""
        seed1 = seed_for_pass("transfer-123", 0, 0)
        seed2 = seed_for_pass("transfer-123", 0, 0)
        
        assert seed1 == seed2
    
    def test_different_transfer_id(self):
        """Test different transfer_id → different seed."""
        seed1 = seed_for_pass("transfer-123", 0, 0)
        seed2 = seed_for_pass("transfer-456", 0, 0)
        
        assert seed1 != seed2
    
    def test_different_window_id(self):
        """Test different window_id → different seed."""
        seed1 = seed_for_pass("transfer-123", 0, 0)
        seed2 = seed_for_pass("transfer-123", 1, 0)
        
        assert seed1 != seed2
    
    def test_different_pass_id(self):
        """Test different pass_id → different seed."""
        seed1 = seed_for_pass("transfer-123", 0, 0)
        seed2 = seed_for_pass("transfer-123", 0, 1)
        
        assert seed1 != seed2
    
    def test_seed_is_64bit(self):
        """Test seed fits in 64 bits."""
        seed = seed_for_pass("test", 0, 0)
        assert 0 <= seed < 2**64
    
    def test_seed_determinism_complex_transfer_id(self):
        """Test with complex UUID-like transfer_id."""
        transfer_id = "550e8400-e29b-41d4-a716-446655440000"
        seed1 = seed_for_pass(transfer_id, 5, 2)
        seed2 = seed_for_pass(transfer_id, 5, 2)
        
        assert seed1 == seed2


class TestGenerateSeeds:
    """Test seed list generation."""
    
    def test_generate_single_pass(self):
        """Test generating seeds for 1 pass."""
        seeds = generate_seeds("transfer-id", 0, 1)
        
        assert len(seeds) == 1
        assert isinstance(seeds[0], int)
    
    def test_generate_three_passes(self):
        """Test generating seeds for 3 passes."""
        seeds = generate_seeds("transfer-id", 0, 3)
        
        assert len(seeds) == 3
        # All different
        assert len(set(seeds)) == 3
    
    def test_generate_invalid_pass_count(self):
        """Test invalid num_passes."""
        with pytest.raises(ValueError):
            generate_seeds("transfer-id", 0, 0)
        
        with pytest.raises(ValueError):
            generate_seeds("transfer-id", 0, 4)
    
    def test_generate_determinism(self):
        """Test list generation is deterministic."""
        seeds1 = generate_seeds("tx-id", 1, 3)
        seeds2 = generate_seeds("tx-id", 1, 3)
        
        assert seeds1 == seeds2
    
    def test_generate_different_windows(self):
        """Test different windows have different seeds."""
        seeds0 = generate_seeds("tx-id", 0, 3)
        seeds1 = generate_seeds("tx-id", 1, 3)
        
        # All 6 seeds should be different
        all_seeds = seeds0 + seeds1
        assert len(set(all_seeds)) == 6


class TestSeedUncorrelation:
    """Test seed uncorrelation (Hamming distance)."""
    
    def test_verify_uncorrelated_passes(self):
        """Test typical transfer has uncorrelated passes."""
        result = verify_seed_uncorrelation("transfer-id", 0, 3)
        assert result is True
    
    def test_verify_uncorrelated_different_windows(self):
        """Test uncorrelation across different windows."""
        for window_id in range(5):
            result = verify_seed_uncorrelation("tx-id", window_id, 3)
            assert result is True
    
    def test_verify_uncorrelated_various_transfers(self):
        """Test uncorrelation across various transfer IDs."""
        transfer_ids = [
            "550e8400-e29b-41d4-a716-446655440000",
            "simple-transfer-id",
            "x",
            "a" * 100,
        ]
        
        for tx_id in transfer_ids:
            result = verify_seed_uncorrelation(tx_id, 0, 3)
            assert result is True
    
    def test_hamming_distance_sufficient(self):
        """Verify at least 20 bits differ between passes."""
        seeds = generate_seeds("test-tx", 0, 2)
        diff = seeds[0] ^ seeds[1]
        hamming = bin(diff).count("1")
        
        # Should have at least 20 bits different (typically much higher)
        assert hamming >= 20
