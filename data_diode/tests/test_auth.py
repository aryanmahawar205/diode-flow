"""
Tests for receiver authentication and manifest verification.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cryptography.hazmat.primitives import serialization
from data_diode.receiver.m14_auth_verifier import (
    AuthVerifier,
    compute_blake3_mac,
    load_ed25519_public_key,
    verify_blake3_mac,
    verify_manifest_signature,
)


class TestAuthVerifier:
    """Authentication verifier tests."""

    def test_compute_blake3_mac_deterministic(self):
        """BLAKE3 MAC should be deterministic for same input and key."""
        key = b"a" * 32
        mac1 = compute_blake3_mac(b"hello", key)
        mac2 = compute_blake3_mac(b"hello", key)
        assert mac1 == mac2
        assert len(mac1) == 32

    def test_verify_blake3_mac_success(self):
        """Valid MAC should verify successfully."""
        key = b"b" * 32
        data = b"packet payload"
        mac = compute_blake3_mac(data, key)
        assert verify_blake3_mac(data, mac, key)

    def test_verify_blake3_mac_failure(self):
        """Invalid MAC should be rejected."""
        key = b"c" * 32
        data = b"packet payload"
        mac = compute_blake3_mac(data, key)
        assert not verify_blake3_mac(data, mac[:-1] + b"x", key)

    def test_manifest_signature_roundtrip(self):
        """Ed25519 manifest signature roundtrip should verify."""
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        message = b"manifest bytes"

        signature = private_key.sign(message)
        assert verify_manifest_signature(message, signature, public_key)

        pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        loaded = load_ed25519_public_key(pem)
        assert verify_manifest_signature(message, signature, loaded)

    def test_auth_verifier_packet(self):
        """AuthVerifier should validate packets correctly."""
        key = b"d" * 32
        verifier = AuthVerifier(shared_secret=key, public_key=Ed25519PrivateKey.generate().public_key())
        data = b"some payload"
        mac = compute_blake3_mac(data, key)
        assert verifier.verify_packet(data, mac)
        assert not verifier.verify_packet(data, mac[:-1] + b"x")

    def test_auth_verifier_manifest(self):
        """AuthVerifier should verify manifest signatures."""
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        verifier = AuthVerifier(shared_secret=b"e" * 32, public_key=public_key)

        message = b"manifest bytes"
        signature = private_key.sign(message)
        assert verifier.verify_manifest(message, signature)
        assert not verifier.verify_manifest(message, signature[:-1] + b"x")
