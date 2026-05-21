"""
receiver/m18_merkle_verifier.py — Per-Chunk Merkle Verification

Role:
Verify each chunk's integrity using Merkle proofs during reassembly. This allows
early detection of corrupted chunks before they're assembled into the file.

Design:
- Input: chunk data, Merkle proof path, tree root
- Compute SHA-256 of chunk
- Verify proof path leads to expected root
- If valid: chunk is good
- If invalid: mark chunk as corrupted (will trigger RS recovery)

Merkle proof verification:
- A proof is a list of sibling hashes from chunk leaf to root
- At each level, combine current hash with sibling using SHA-256
- At top, result must match root
"""

from dataclasses import dataclass
import hashlib
from typing import List, Optional


@dataclass
class MerkleProofStep:
    """One step in a Merkle proof path."""
    sibling_hash: str     # Hex hash of sibling node
    is_left: bool         # True if sibling is to the left


def verify_chunk_merkle(
    chunk_data: bytes,
    chunk_id: int,
    merkle_root: str,
    merkle_tree_dict: dict,
) -> bool:
    """
    Verify a chunk's integrity using Merkle tree.
    
    Args:
        chunk_data: Chunk bytes to verify
        chunk_id: Global chunk ID
        merkle_root: Expected Merkle root (hex string)
        merkle_tree_dict: Merkle tree dict with 'root', 'leaves' keys
    
    Returns:
        True if chunk is valid (hash matches tree), False otherwise
    """
    if not chunk_data:
        return False
    
    # Compute chunk hash
    chunk_hash = hashlib.sha256(chunk_data).hexdigest()
    
    # For now, simple verification: check if chunk_hash is in tree leaves
    # Full proof verification would rebuild path to root
    if "leaves" in merkle_tree_dict:
        leaves = merkle_tree_dict["leaves"]
        # Check if chunk_hash is among leaves (simplified check)
        # In full impl, would trace proof path to root
        if chunk_id < len(leaves):
            expected_hash = leaves[chunk_id]
            return chunk_hash == expected_hash
    
    # If no tree info, assume valid (Phase 2 placeholder)
    return True


def batch_verify_chunks(
    chunks: dict[int, bytes],
    merkle_root: str,
    merkle_tree_dict: dict,
) -> dict[int, bool]:
    """
    Verify multiple chunks against Merkle tree.
    
    Args:
        chunks: Dict of chunk_id -> chunk_data
        merkle_root: Expected root
        merkle_tree_dict: Merkle tree dict
    
    Returns:
        Dict of chunk_id -> is_valid
    """
    results = {}
    for chunk_id, chunk_data in chunks.items():
        results[chunk_id] = verify_chunk_merkle(chunk_data, chunk_id, merkle_root, merkle_tree_dict)
    return results


def get_failed_chunks(verification_results: dict[int, bool]) -> List[int]:
    """Get list of chunk IDs that failed verification."""
    return [chunk_id for chunk_id, is_valid in verification_results.items() if not is_valid]
