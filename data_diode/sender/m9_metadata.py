"""
sender/m9_metadata.py — Metadata + Auth Tag Generator
"""

import hashlib
import hmac
import crcmod
import blake3
from cryptography.hazmat.primitives.asymmetric import ed25519

# crcmod at module level
_CRC32C = crcmod.mkCrcFun(0x11EDC6F41, rev=True, initCrc=0xffffffff, xorOut=0xffffffff)


def compute_crc32c(data: bytes) -> int:
    """Compute CRC32C checksum."""
    return _CRC32C(data) & 0xffffffff


def compute_blake3_mac(data: bytes, shared_secret: bytes) -> bytes:
    """Compute BLAKE3-MAC over data using shared secret."""
    if len(shared_secret) != 32:
        raise ValueError(f"shared_secret must be 32 bytes, got {len(shared_secret)}")
    h = blake3.blake3(key=shared_secret)
    h.update(data)
    return h.digest()


def verify_blake3_mac(data: bytes, mac: bytes, shared_secret: bytes) -> bool:
    """Verify BLAKE3-MAC using timing-safe comparison."""
    expected = compute_blake3_mac(data, shared_secret)
    return hmac.compare_digest(mac, expected)


def sign_manifest(manifest_bytes: bytes, private_key: ed25519.Ed25519PrivateKey) -> bytes:
    """Sign manifest with Ed25519."""
    return private_key.sign(manifest_bytes)


def verify_manifest_signature(manifest_bytes: bytes, signature: bytes, public_key: ed25519.Ed25519PublicKey) -> bool:
    """Verify manifest signature."""
    try:
        public_key.verify(signature, manifest_bytes)
        return True
    except Exception:
        return False


def generate_ed25519_keypair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Generate new Ed25519 keypair."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


from cryptography.hazmat.primitives import serialization

def export_private_key(private_key: ed25519.Ed25519PrivateKey) -> bytes:
    """Export private key to PEM."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def export_public_key(public_key: ed25519.Ed25519PublicKey) -> bytes:
    """Export public key to PEM."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def import_private_key(pem_bytes: bytes) -> ed25519.Ed25519PrivateKey:
    """Import private key from PEM."""
    return serialization.load_pem_private_key(pem_bytes, password=None)


def import_public_key(pem_bytes: bytes) -> ed25519.Ed25519PublicKey:
    """Import public key from PEM."""
    return serialization.load_pem_public_key(pem_bytes)
