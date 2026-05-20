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


def verify_seed_uncorrelation(transfer_id: str, window_id: int, num_passes: int) -> bool:
    """
    Verify that seeds from different passes are uncorrelated (bitwise Hamming distance).
    
    For debugging: returns True if passes have good bit separation (sanity check).
    This is not cryptographic validation — just ensures seeds differ significantly.
    
    Args:
        transfer_id: Transfer UUID
        window_id: Window index
        num_passes: Number of passes
    
    Returns:
        True if seeds are sufficiently uncorrelated
    """
    seeds = generate_seeds(transfer_id, window_id, num_passes)
    
    # Check each pair
    for i in range(len(seeds)):
        for j in range(i + 1, len(seeds)):
            # XOR to find different bits
            diff = seeds[i] ^ seeds[j]
            # Count differing bits (Hamming distance)
            hamming = bin(diff).count("1")
            # Should have at least 30 bits different (for 64-bit seeds)
            if hamming < 30:
                return False
    
    return True
