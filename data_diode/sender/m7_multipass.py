"""
sender/m7_multipass.py — Multi-Pass Seed Generator

Role:
Generates independent, deterministic seeds for each pass of a given
transfer+window combination. Seeds must be:
1. Deterministic: same transfer_id + window_id → same seeds always
2. Uncorrelated: seeds for different passes produce maximally different XOR combos
3. Reproducible: stored in manifest so receiver can verify

Design:
Seed derivation via SHA-256:
  seed_for_pass_i = int(SHA-256(transfer_id:window_id:pass_i)[:8], big-endian)

This guarantees:
- Same parameters → identical seed (deterministic)
- Different pass_i → completely different seed (uncorrelated)
- No shared state between passes (independent encoding)

Why deterministic seeds?
- Receiver can regenerate all seeds from manifest
- Reproducible debugging
- Protocol compliance: both sender/receiver generate same seeds independently
"""

import hashlib
from typing import List


def seed_for_pass(transfer_id: str, window_id: int, pass_id: int) -> int:
    """
    Generate deterministic seed for one pass.
    
    Args:
        transfer_id: Transfer UUID (string)
        window_id: Window index (0-based)
        pass_id: Pass index within window (0, 1, 2, ...)
    
    Returns:
        Seed as 64-bit unsigned integer
    
    Determinism: Same inputs → identical seed
    Uncorrelation: Different pass_id → completely different seed (SHA-256)
    """
    raw = f"{transfer_id}:{window_id}:{pass_id}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    # Take first 8 bytes, interpret as big-endian unsigned 64-bit
    seed = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return seed


def generate_seeds(transfer_id: str, window_id: int, num_passes: int) -> List[int]:
    """
    Generate all seeds for one window.
    
    Args:
        transfer_id: Transfer UUID
        window_id: Window index
        num_passes: Number of passes (1-3)
    
    Returns:
        List of seeds for pass 0, 1, ..., num_passes-1
    """
    if num_passes < 1 or num_passes > 3:
        raise ValueError(f"num_passes must be 1-3, got {num_passes}")
    
    return [seed_for_pass(transfer_id, window_id, pass_id) for pass_id in range(num_passes)]


def verify_seed_uncorrelation(
    transfer_id_or_seed0,
    window_id_or_seed1,
    num_passes: int | None = None,
    threshold: int = 20,
) -> bool:
    """
    Verify that seeds are uncorrelated.

    Supports two usage patterns:
    1. verify_seed_uncorrelation(transfer_id, window_id, num_passes)
       - Generates seeds for a transfer and verifies pairwise Hamming distance.
    2. verify_seed_uncorrelation(seed0, seed1, threshold=20)
       - Verifies two already-generated seeds are sufficiently different.
    """
    # Pattern 1: transfer_id / window_id / num_passes
    if isinstance(transfer_id_or_seed0, str) and isinstance(window_id_or_seed1, int):
        if num_passes is None:
            raise ValueError("num_passes must be provided for transfer_id mode")
        seeds = generate_seeds(transfer_id_or_seed0, window_id_or_seed1, num_passes)
    # Pattern 2: seed0 / seed1 / threshold
    elif isinstance(transfer_id_or_seed0, int) and isinstance(window_id_or_seed1, int):
        seeds = [transfer_id_or_seed0, window_id_or_seed1]
        if num_passes is not None:
            threshold = num_passes
    else:
        raise TypeError(
            "verify_seed_uncorrelation() expects either "
            "(transfer_id: str, window_id: int, num_passes: int) "
            "or (seed0: int, seed1: int, threshold: int)"
        )

    # Check each pair
    for i in range(len(seeds)):
        for j in range(i + 1, len(seeds)):
            diff = seeds[i] ^ seeds[j]
            hamming = bin(diff).count("1")
            if hamming < threshold:
                return False

    return True
