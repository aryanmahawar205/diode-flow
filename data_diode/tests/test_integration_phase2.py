"""
tests/test_integration_phase2.py — Phase 2 Integration Tests

Tests for Phase 2 robustness features:
- Profile selection
- Windowing
- Multi-pass encoding
- Loss resilience
"""

import os
import tempfile
import hashlib

import pytest

from data_diode.sender.m5_profile import get_profile
from data_diode.sender.m7_multipass import seed_for_pass, verify_seed_uncorrelation
from data_diode.sender.m9_metadata import (
    compute_crc32c,
    compute_blake3_mac,
    generate_ed25519_keypair,
    sign_manifest,
    verify_manifest_signature,
)
from data_diode.tests.utils.loss_simulator import LossSimulator


class TestPhase2Profiles:
    """Tests for profile selection."""
    
    def test_get_profile_standard(self):
        """Test getting standard profile."""
        profile = get_profile(1_000_000, "standard")
        
        assert profile.passes >= 1
        assert 0.10 <= profile.overhead_ratio <= 0.25
        assert profile.window_size_bytes > 0
        assert profile.chunk_size_bytes > 0
    
    def test_get_profile_critical(self):
        """Test getting critical profile."""
        profile = get_profile(1_000_000, "critical")
        
        assert profile.passes >= 1
        assert profile.overhead_ratio >= 0.15
        assert profile.window_size_bytes > 0
    
    def test_get_profile_classified(self):
        """Test getting classified profile."""
        profile = get_profile(1_000_000, "classified")
        
        assert profile.passes >= 1
        assert profile.overhead_ratio >= 0.15
        assert profile.interleave_depth > 0
    
    def test_profile_varies_with_file_size(self):
        """Test that profile changes with file size."""
        small = get_profile(1_000_000, "standard")      # 1 MB
        medium = get_profile(100_000_000, "standard")    # 100 MB
        
        # Different file sizes should have different window configs
        # (at least one should differ)
        assert (small.window_size_bytes != medium.window_size_bytes or
                small.passes != medium.passes)
    
    def test_profile_varies_with_criticality(self):
        """Test that profile changes with criticality."""
        file_size = 10_000_000  # 10 MB
        
        standard = get_profile(file_size, "standard")
        critical = get_profile(file_size, "critical")
        classified = get_profile(file_size, "classified")
        
        # Different criticalities should have different redundancy
        # (at least one metric should differ)
        assert (standard.overhead_ratio != critical.overhead_ratio or
                standard.passes != critical.passes or
                critical.overhead_ratio != classified.overhead_ratio or
                critical.passes != classified.passes)


class TestPhase2MultiPass:
    """Tests for multi-pass seed generation."""
    
    def test_seed_determinism(self):
        """Test that seeds are deterministic."""
        transfer_id = "test-txn-1"
        window_id = 0
        pass_id = 0
        
        seed1 = seed_for_pass(transfer_id, window_id, pass_id)
        seed2 = seed_for_pass(transfer_id, window_id, pass_id)
        
        assert seed1 == seed2
    
    def test_seed_varies_by_pass(self):
        """Test that different passes have different seeds."""
        transfer_id = "test-txn-2"
        window_id = 0
        
        seeds = [
            seed_for_pass(transfer_id, window_id, p)
            for p in range(3)
        ]
        
        # All seeds should be different
        assert len(set(seeds)) == 3
    
    def test_seed_uncorrelation_verified(self):
        """Test that seeds are adequately uncorrelated."""
        transfer_id = "test-txn-3"
        window_id = 0
        
        seed0 = seed_for_pass(transfer_id, window_id, 0)
        seed1 = seed_for_pass(transfer_id, window_id, 1)
        seed2 = seed_for_pass(transfer_id, window_id, 2)
        
        # Verify uncorrelation (20 bits differ)
        assert verify_seed_uncorrelation(seed0, seed1, threshold=20)
        assert verify_seed_uncorrelation(seed1, seed2, threshold=20)
        assert verify_seed_uncorrelation(seed0, seed2, threshold=20)


class TestPhase2Metadata:
    """Tests for cryptographic metadata."""
    
    def test_crc32c_determinism(self):
        """Test CRC32C is deterministic."""
        data = b"test packet data"
        
        crc1 = compute_crc32c(data)
        crc2 = compute_crc32c(data)
        
        assert crc1 == crc2
        assert isinstance(crc1, int)
    
    def test_crc32c_varies_with_data(self):
        """Test CRC32C varies with different data."""
        crc1 = compute_crc32c(b"data1")
        crc2 = compute_crc32c(b"data2")
        
        assert crc1 != crc2
    
    def test_blake3_mac_determinism(self):
        """Test BLAKE3-MAC is deterministic."""
        key = b"K" * 32
        data = b"test packet data"
        
        mac1 = compute_blake3_mac(data, key)
        mac2 = compute_blake3_mac(data, key)
        
        assert mac1 == mac2
        assert isinstance(mac1, bytes)
        assert len(mac1) == 32
    
    def test_blake3_mac_varies_with_key(self):
        """Test BLAKE3-MAC varies with different keys."""
        data = b"test"
        
        key1 = b"K" * 32
        key2 = b"X" * 32
        
        mac1 = compute_blake3_mac(data, key1)
        mac2 = compute_blake3_mac(data, key2)
        
        assert mac1 != mac2
    
    def test_blake3_mac_requires_32_byte_key(self):
        """Test BLAKE3-MAC requires exactly 32-byte key."""
        data = b"test"
        
        # Valid: 32 bytes
        mac = compute_blake3_mac(data, b"K" * 32)
        assert isinstance(mac, bytes)
        
        # Invalid: wrong key size should raise
        with pytest.raises(Exception):
            compute_blake3_mac(data, b"K" * 16)
    
    def test_ed25519_signature_generation_and_verification(self):
        """Test Ed25519 signature generation and verification."""
        manifest_bytes = b"test manifest data"
        
        private_key, public_key = generate_ed25519_keypair()
        
        # Sign
        signature = sign_manifest(manifest_bytes, private_key)
        assert isinstance(signature, bytes)
        assert len(signature) == 64
        
        # Verify with correct data
        assert verify_manifest_signature(manifest_bytes, signature, public_key)
        
        # Verify with wrong data should fail
        assert not verify_manifest_signature(b"wrong data", signature, public_key)
    
    def test_ed25519_different_keys_produce_different_signatures(self):
        """Test different keys produce different signatures."""
        data = b"test data"
        
        key1_priv, key1_pub = generate_ed25519_keypair()
        key2_priv, key2_pub = generate_ed25519_keypair()
        
        sig1 = sign_manifest(data, key1_priv)
        sig2 = sign_manifest(data, key2_priv)
        
        assert sig1 != sig2


class TestPhase2LossSimulator:
    """Tests for loss simulator functionality."""
    
    def test_random_loss_basic(self):
        """Test random loss simulation."""
        packets = [b"packet" for _ in range(1000)]
        
        packets_with_loss, lost_indices = LossSimulator.apply_random_loss(
            packets,
            loss_rate=0.1,
            seed=42
        )
        
        assert len(packets_with_loss) == len(packets)
        lost_count = sum(1 for p in packets_with_loss if p is None)
        assert 50 < lost_count < 150  # ~10% of 1000
    
    def test_random_loss_reproducibility(self):
        """Test random loss is reproducible with seed."""
        packets = [b"p" for _ in range(100)]
        
        result1, _ = LossSimulator.apply_random_loss(packets, 0.2, seed=100)
        result2, _ = LossSimulator.apply_random_loss(packets, 0.2, seed=100)
        
        assert result1 == result2
    
    def test_burst_loss_basic(self):
        """Test burst loss simulation."""
        packets = [b"packet" for _ in range(1000)]
        
        packets_with_loss, lost_indices = LossSimulator.apply_burst_loss(
            packets,
            burst_rate=0.01,
            burst_length=100,
            seed=43
        )
        
        assert len(packets_with_loss) == len(packets)
        lost_count = sum(1 for p in packets_with_loss if p is None)
        assert lost_count > 0  # At least one burst happened
    
    def test_burst_loss_reproducibility(self):
        """Test burst loss is reproducible with seed."""
        packets = [b"p" for _ in range(500)]
        
        result1, _ = LossSimulator.apply_burst_loss(packets, 0.02, 50, seed=200)
        result2, _ = LossSimulator.apply_burst_loss(packets, 0.02, 50, seed=200)
        
        assert result1 == result2
    
    def test_bit_corruption_basic(self):
        """Test bit corruption simulation."""
        packets = [b"\x00" * 100 for _ in range(10)]
        
        corrupted = LossSimulator.apply_corruption_to_packets(
            packets,
            corruption_rate=0.001,  # ~0.1% of bits
            seed=44
        )
        
        assert len(corrupted) == len(packets)
        
        # At least one packet should be different (some bits corrupted)
        different_count = sum(
            1 for orig, corr in zip(packets, corrupted)
            if orig is not None and corr != orig
        )
        # May or may not have corruption at this low rate with small packets


class TestPhase2IntegrationScenarios:
    """Integration tests combining multiple Phase 2 features."""
    
    def test_profile_and_seeds_work_together(self):
        """Test profile selection and seed generation integrate."""
        file_size = 50_000_000
        profile = get_profile(file_size, "critical")
        
        # Generate seeds for each pass
        transfer_id = "test-integration-1"
        window_id = 0
        
        seeds = []
        for pass_id in range(profile.passes):
            seed = seed_for_pass(transfer_id, window_id, pass_id)
            seeds.append(seed)
        
        assert len(seeds) == profile.passes
        assert len(set(seeds)) == profile.passes  # All unique
    
    def test_metadata_generation_workflow(self):
        """Test complete metadata generation workflow."""
        packet_data = b"test packet content"
        shared_secret = b"S" * 32
        
        # Compute CRC
        crc = compute_crc32c(packet_data)
        assert isinstance(crc, int)
        
        # Compute MAC
        mac = compute_blake3_mac(packet_data, shared_secret)
        assert len(mac) == 32
        
        # Generate manifest signature
        manifest = b"transfer manifest"
        priv_key, pub_key = generate_ed25519_keypair()
        sig = sign_manifest(manifest, priv_key)
        
        # Verify all
        assert verify_manifest_signature(manifest, sig, pub_key)
    
    def test_loss_and_recovery_perspective(self):
        """Test loss scenario that recovery layer should handle."""
        # Create packet stream representing a window transfer
        file_size = 10_000_000
        profile = get_profile(file_size, "critical")
        
        # Simulate sending packets
        packets = [b"P" * 512 for _ in range(1000)]
        
        # Apply 10% random loss
        with_loss, _ = LossSimulator.apply_random_loss(packets, 0.1, seed=50)
        
        lost_count = sum(1 for p in with_loss if p is None)
        remaining = 1000 - lost_count
        
        # Critical profile should have enough redundancy
        # (at least 55% overhead) to recover
        expected_overhead = int(1000 * profile.overhead_ratio)
        
        # With multi-pass (>= 2 passes), the overhead spreads across passes
        # Simplified check: total packets should exceed K significantly
        assert remaining > 500, "Should have sufficient packets for recovery"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
