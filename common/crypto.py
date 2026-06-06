from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


KEY_DIR = Path("keys")
PRIVATE_KEY_FILE = KEY_DIR / "sender_private.pem"
PUBLIC_KEY_FILE = KEY_DIR / "sender_public.pem"


def generate_keys_if_missing():
    KEY_DIR.mkdir(exist_ok=True)

    if PRIVATE_KEY_FILE.exists() and PUBLIC_KEY_FILE.exists():
        return

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    PRIVATE_KEY_FILE.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    PUBLIC_KEY_FILE.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def load_private_key() -> Ed25519PrivateKey:
    generate_keys_if_missing()

    return serialization.load_pem_private_key(
        PRIVATE_KEY_FILE.read_bytes(),
        password=None,
    )


def load_public_key() -> Ed25519PublicKey:
    generate_keys_if_missing()

    return serialization.load_pem_public_key(
        PUBLIC_KEY_FILE.read_bytes()
    )


def manifest_payload(manifest_dict: dict) -> bytes:
    """
    Canonical bytes for signing.
    Excludes signature field itself.
    """

    clean = dict(manifest_dict)

    clean.pop("ed25519_signature", None)

    return json.dumps(
        clean,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def sign_manifest(manifest_dict: dict) -> bytes:
    private_key = load_private_key()

    payload = manifest_payload(manifest_dict)

    return private_key.sign(payload)


def verify_manifest(manifest_dict: dict, signature: bytes) -> bool:
    try:
        public_key = load_public_key()

        payload = manifest_payload(manifest_dict)

        public_key.verify(signature, payload)

        return True

    except Exception as e:
        print("ED25519 VERIFY FAILED:", e)
        return False