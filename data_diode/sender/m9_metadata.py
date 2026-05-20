"""
sender/m9_metadata.py — Metadata + Auth Tag Generator

Role:
Attaches the full security envelope to each packet before serialization.
Two cryptographic layers:

Layer 1 — CRC32C (per packet, fast):
  - Computed over serialized packet payload
  - Used by receiver for fast corrupt-packet rejection before crypto
  - CRC32C (Castagnoli) better polynomial, HW-accelerated on x86/ARM

Layer 2 — BLAKE3-MAC (per packet, cryptographic):
  - BLAKE3(key=shared_secret, data=serialized_packet)
  - Shared secret: pre-configured symmetric key (set at deployment time)
  - Catches adversarial tampering that CRC32C cannot detect
  - BLAKE3 chosen: faster than HMAC-SHA256, parallelizable, modern

Ed25519 signature (per manifest, not per packet):
  - Signs: manifest_bytes + merkle_root + transfer_id
  - Private key held by sender, public key pre-distributed to receiver
  - Verifies sender authenticity — not just data integrity

Full packet envelope:
  ┌─────────────────────────────────┐
  │ [metadata fields] (20+ bytes)   │
  │ [payload bytes]                 │
  ├─────────────────────────────────┤
  │ crc32c: computed over [metadata + payload]
  │ blake3_mac: computed over [metadata + payload]
  └─────────────────────────────────┘
"""

import hashlib
import crcmod
import blake3
from typing import Optional
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization


# CRC32C polynomial (Castagnoli) — pre-computed by crcmod
_CRC32C_POLY = 0x11EDC6F41  # bit-reversed CRC-32C polynomial
_CRC32C_FUNC = crcmod.mkCrcFun(_CRC32C_POLY, rev=True, initCrc=0xffffffff, xorOut=0xffffffff)


def compute_crc32c(data: bytes) -> int:
    """
    Compute CRC32C checksum over data.
    
    Args:
        data: Bytes to checksum
    
    Returns:
        CRC32C as 32-bit unsigned integer
    """
    return _CRC32C_FUNC(data) & 0xffffffff


def compute_blake3_mac(data: bytes, shared_secret: bytes) -> bytes:
    """
    Compute BLAKE3-MAC over data using shared secret.
    
    Args:
        data: Bytes to MAC
        shared_secret: Pre-shared symmetric key (typically 32 bytes)
    
    Returns:
        BLAKE3-MAC as 32-byte digest
    """
    h = blake3.blake3(key=shared_secret)
    h.update(data)
    return h.digest()


def sign_manifest(manifest_bytes: bytes, private_key: ed25519.Ed25519PrivateKey) -> bytes:
    """
    Sign manifest with Ed25519 private key.
    
    Args:
        manifest_bytes: Serialized manifest
        private_key: Ed25519 private key
    
    Returns:
        Signature bytes (64 bytes for Ed25519)
    """
    signature = private_key.sign(manifest_bytes)
    return signature


def verify_manifest_signature(manifest_bytes: bytes, signature: bytes, public_key: ed25519.Ed25519PublicKey) -> bool:
    """
    Verify manifest signature with Ed25519 public key.
    
    Args:
        manifest_bytes: Serialized manifest
        signature: Signature bytes
        public_key: Ed25519 public key
    
    Returns:
        True if signature valid, False otherwise
    """
    try:
        public_key.verify(signature, manifest_bytes)
        return True
    except Exception:
        return False


def generate_ed25519_keypair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """
    Generate new Ed25519 keypair.
    
    Returns:
        (private_key, public_key) tuple
    """
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def export_private_key(private_key: ed25519.Ed25519PrivateKey) -> bytes:
    """Export private key to PEM format."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def export_public_key(public_key: ed25519.Ed25519PublicKey) -> bytes:
    """Export public key to PEM format."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def import_private_key(pem_bytes: bytes) -> ed25519.Ed25519PrivateKey:
    """Import private key from PEM format."""
    return serialization.load_pem_private_key(pem_bytes, password=None)


def import_public_key(pem_bytes: bytes) -> ed25519.Ed25519PublicKey:
    """Import public key from PEM format."""
    return serialization.load_pem_public_key(pem_bytes)


class PacketEnvelope:
    """Security envelope wrapper for a packet."""
    
    def __init__(self, payload: bytes, shared_secret: bytes):
        """
        Initialize packet envelope.
        
        Args:
            payload: Packet payload bytes
            shared_secret: BLAKE3 shared secret (typically 32 bytes)
        """
        self.payload = payload
        self.shared_secret = shared_secret
        self.crc32c = None
        self.blake3_mac = None
    
    def compute_checksums(self) -> None:
        """Compute CRC32C and BLAKE3-MAC for payload."""
        self.crc32c = compute_crc32c(self.payload)
        self.blake3_mac = compute_blake3_mac(self.payload, self.shared_secret)
    
    def verify_crc32c(self, crc32c: int) -> bool:
        """Verify CRC32C checksum."""
        return crc32c == compute_crc32c(self.payload)
    
    def verify_blake3_mac(self, mac: bytes) -> bool:
        """Verify BLAKE3-MAC."""
        expected = compute_blake3_mac(self.payload, self.shared_secret)
        return mac == expected
