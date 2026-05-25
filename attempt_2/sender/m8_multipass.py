"""
Deterministic seed generation for multi-pass fountain encoding.
SHA-256(transfer_id:window_id:pass_id) → 64-bit seed.
Same inputs always produce same seed (deterministic).
Different pass_ids produce completely different seeds (uncorrelated).
"""
from __future__ import annotations
import hashlib


def seed_for_pass(transfer_id: str, window_id: int, pass_id: int) -> int:
    raw    = f"{transfer_id}:{window_id}:{pass_id}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], byteorder="big")


def all_seeds(transfer_id: str, window_id: int, num_passes: int) -> list[int]:
    return [seed_for_pass(transfer_id, window_id, p) for p in range(num_passes)]
