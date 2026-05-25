"""
tests/test_metadata.py — Metadata & Auth Tag Tests

Tests for sender/m9_metadata.py:
- CRC32C computation and verification
- BLAKE3-MAC computation and verification
- Ed25519 keypair generation, signing, verification
- PacketEnvelope class
"""

import pytest
from sender.m9_metadata import (
    compute_crc32c,
    compute_blake3_mac,
    verify_blake3_mac,
    generate_ed25519_keypair,
    sign_manifest,
    verify_manifest_signature,
    export_private_key,
    export_public_key,
    import_private_key,
    import_public_key,
)


class TestCRC32C:
    """Test CRC32C computation."""
    
    def test_crc32c_determinism(self):
        """Test same data → same CRC32C."""
        data = b"Hello, World!"
        crc1 = compute_crc32c(data)
        crc2 = compute_crc32c(data)
        
        assert crc1 == crc2
    
    def test_crc32c_different_data(self):
        """Test different data → different CRC32C."""
        crc1 = compute_crc32c(b"Hello")
        crc2 = compute_crc32c(b"World")
        
        assert crc1 != crc2
    
    def test_crc32c_fits_32bit(self):
        """Test CRC32C fits in 32 bits."""
        crc = compute_crc32c(b"test data")
        assert 0 <= crc < 2**32
    
    def test_crc32c_empty_data(self):
        """Test CRC32C of empty data."""
        crc = compute_crc32c(b"")
        # Should be consistent
        assert isinstance(crc, int)
    
    def test_crc32c_large_data(self):
        """Test CRC32C of large data."""
        data = b"X" * 1000000
        crc = compute_crc32c(data)
        assert 0 <= crc < 2**32


class TestBLAKE3MAC:
    """Test BLAKE3-MAC computation."""
    
    def test_blake3_mac_determinism(self):
        """Test same data + key → same MAC."""
        data = b"payload"
        key = b"K" * 32  # blake3 requires exactly 32-byte key
        
        mac1 = compute_blake3_mac(data, key)
        mac2 = compute_blake3_mac(data, key)
        
        assert mac1 == mac2
    
    def test_blake3_mac_different_data(self):
        """Test different data → different MAC."""
        key = b"K" * 32
        mac1 = compute_blake3_mac(b"data1", key)
        mac2 = compute_blake3_mac(b"data2", key)
        
        assert mac1 != mac2
    
    def test_blake3_mac_different_key(self):
        """Test different key → different MAC."""
        data = b"payload"
        mac1 = compute_blake3_mac(data, b"K" * 32)
        mac2 = compute_blake3_mac(data, b"D" * 32)
        
        assert mac1 != mac2
    
    def test_blake3_mac_is_32bytes(self):
        """Test MAC is 32 bytes."""
        mac = compute_blake3_mac(b"test", b"X" * 32)
        assert len(mac) == 32
        assert isinstance(mac, bytes)
    
    def test_blake3_mac_empty_key(self):
        """Test with empty key raises ValueError."""
        with pytest.raises(ValueError):
            compute_blake3_mac(b"data", b"")
    
    def test_blake3_mac_short_key(self):
        """Test with key shorter than 32 bytes raises ValueError."""
        with pytest.raises(ValueError):
            compute_blake3_mac(b"data", b"short")


class TestEd25519:
    """Test Ed25519 key generation and signing."""
    
    def test_keypair_generation(self):
        """Test keypair generation."""
        private_key, public_key = generate_ed25519_keypair()
        
        assert private_key is not None
        assert public_key is not None
    
    def test_different_keypairs(self):
        """Test generating keypairs produces different keys."""
        priv1, pub1 = generate_ed25519_keypair()
        priv2, pub2 = generate_ed25519_keypair()
        
        # Keys should be different (extremely high probability)
        pub1_bytes = export_public_key(pub1)
        pub2_bytes = export_public_key(pub2)
        assert pub1_bytes != pub2_bytes
    
    def test_sign_and_verify(self):
        """Test signing and verification."""
        private_key, public_key = generate_ed25519_keypair()
        manifest = b"Test manifest data"
        
        signature = sign_manifest(manifest, private_key)
        
        # Should verify successfully
        assert verify_manifest_signature(manifest, signature, public_key) is True
    
    def test_verify_wrong_manifest(self):
        """Test verification fails with wrong data."""
        private_key, public_key = generate_ed25519_keypair()
        manifest = b"Original data"
        
        signature = sign_manifest(manifest, private_key)
        
        # Verification should fail for different data
        assert verify_manifest_signature(b"Modified data", signature, public_key) is False
    
    def test_verify_wrong_key(self):
        """Test verification fails with wrong key."""
        priv1, pub1 = generate_ed25519_keypair()
        priv2, pub2 = generate_ed25519_keypair()
        
        manifest = b"Test data"
        signature = sign_manifest(manifest, priv1)
        
        # Should fail with different public key
        assert verify_manifest_signature(manifest, signature, pub2) is False
    
    def test_signature_determinism(self):
        """Test signing same data twice produces same signature."""
        private_key, _ = generate_ed25519_keypair()
        manifest = b"Test manifest"
        
        sig1 = sign_manifest(manifest, private_key)
        sig2 = sign_manifest(manifest, private_key)
        
        assert sig1 == sig2
    
    def test_signature_is_64bytes(self):
        """Test Ed25519 signature is 64 bytes."""
        private_key, _ = generate_ed25519_keypair()
        signature = sign_manifest(b"data", private_key)
        
        assert len(signature) == 64


class TestKeyExportImport:
    """Test key export/import to/from PEM."""
    
    def test_export_private_key(self):
        """Test exporting private key to PEM."""
        private_key, _ = generate_ed25519_keypair()
        pem = export_private_key(private_key)
        
        assert b"BEGIN PRIVATE KEY" in pem
        assert isinstance(pem, bytes)
    
    def test_export_public_key(self):
        """Test exporting public key to PEM."""
        _, public_key = generate_ed25519_keypair()
        pem = export_public_key(public_key)
        
        assert b"BEGIN PUBLIC KEY" in pem
        assert isinstance(pem, bytes)
    
    def test_roundtrip_private_key(self):
        """Test private key export/import round-trip."""
        original_key, _ = generate_ed25519_keypair()
        pem = export_private_key(original_key)
        
        imported_key = import_private_key(pem)
        
        # Test that imported key works for signing
        manifest = b"test"
        sig = sign_manifest(manifest, imported_key)
        public_key = original_key.public_key()
        
        assert verify_manifest_signature(manifest, sig, public_key) is True
