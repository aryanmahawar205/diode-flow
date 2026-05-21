"""
receiver/m14_auth_verifier.py — Authentication verifier for receiver pipeline.

Role:
Verify per-packet BLAKE3-MACs and manifest Ed25519 signatures.

Design:
- Load Ed25519 public key from PEM
- Verify manifest signature in constant time
- Verify packet MAC in constant time
- Fail silently for invalid packets, but log reasons for diagnostics
"""

from __future__ import annotations

import hmac
import logging
from typing import Optional

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

logger = logging.getLogger(__name__)


def load_ed25519_public_key(pem_bytes: bytes) -> Ed25519PublicKey:
    """
    Load an Ed25519 public key from PEM bytes.

    Parameters:
        pem_bytes: PEM-encoded public key bytes.

    Returns:
        Ed25519PublicKey instance.
    """
    return load_pem_public_key(pem_bytes)


def compute_blake3_mac(data: bytes, shared_secret: bytes) -> bytes:
    """
    Compute a BLAKE3 MAC over data using a 32-byte shared secret.

    Parameters:
        data: Message bytes.
        shared_secret: Key bytes.

    Returns:
        32-byte MAC.

    Raises:
        ValueError: if shared_secret length is not 32.
    """
    if len(shared_secret) != 32:
        raise ValueError(
            f"shared_secret must be exactly 32 bytes, got {len(shared_secret)}"
        )

    h = blake3.blake3(key=shared_secret)
    h.update(data)
    return h.digest()


def verify_blake3_mac(
    data: bytes,
    expected_mac: bytes,
    shared_secret: bytes,
) -> bool:
    """
    Verify a BLAKE3 MAC in constant time.

    Parameters:
        data: Message bytes.
        expected_mac: Expected MAC bytes.
        shared_secret: Shared secret key.

    Returns:
        True if MAC matches, False otherwise.
    """
    if not expected_mac or len(expected_mac) != 32:
        logger.warning("Invalid BLAKE3 MAC length")
        return False

    mac = compute_blake3_mac(data, shared_secret)
    return hmac.compare_digest(mac, expected_mac)


def verify_manifest_signature(
    manifest_bytes: bytes,
    signature: bytes,
    public_key: Ed25519PublicKey,
) -> bool:
    """
    Verify the Ed25519 signature on the transfer manifest.

    Parameters:
        manifest_bytes: Serialized manifest bytes.
        signature: Signature bytes.
        public_key: Ed25519 public key.

    Returns:
        True if signature is valid, False otherwise.
    """
    try:
        public_key.verify(signature, manifest_bytes)
        return True
    except InvalidSignature:
        logger.warning("Ed25519 manifest signature verification failed")
        return False
    except Exception as exc:
        logger.error(f"Unexpected error verifying manifest signature: {exc}")
        return False


class AuthVerifier:
    """
    Receiver-side auth verifier for packets and manifests.
    """

    def __init__(self, shared_secret: bytes, public_key: Ed25519PublicKey):
        self.shared_secret = shared_secret
        self.public_key = public_key

        if len(self.shared_secret) != 32:
            raise ValueError(
                f"shared_secret must be 32 bytes, got {len(self.shared_secret)}"
            )

    def verify_packet(self, payload: bytes, blake3_mac: bytes) -> bool:
        """
        Verify packet integrity using BLAKE3-MAC.
        """
        valid = verify_blake3_mac(payload, blake3_mac, self.shared_secret)
        if not valid:
            logger.warning("Packet failed BLAKE3-MAC verification")
        return valid

    def verify_manifest(self, manifest_bytes: bytes, signature: bytes) -> bool:
        """
        Verify manifest authenticity using Ed25519.
        """
        valid = verify_manifest_signature(manifest_bytes, signature, self.public_key)
        if not valid:
            logger.warning("Manifest failed Ed25519 verification")
        return valid
