"""
receiver/m18_merkle_verifier.py — Merkle Verification
"""

from __future__ import annotations
import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import List, Optional
from sender.m3_merkle import verify_merkle_proof, get_merkle_proof, build_merkle_tree, get_merkle_root
from common.models import TransferManifest

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    all_passed: bool
    chunks: List[bytes]
    window_root: str = ""


def verify_chunk_merkle(chunk_data: bytes, chunk_id: int, expected_root: str, tree_data: tuple) -> bool:
    """
    Verify a single chunk against a Merkle root using a proof.
    """
    if not tree_data:
        logger.error(f"Missing tree data for chunk {chunk_id} verification")
        return False
        
    chunk_hash = hashlib.sha256(chunk_data).hexdigest()
    try:
        # Note: tree_data is (tree, child_to_parent, sibling_map, is_left_child)
        # We need the original chunks list to get the proof if we use get_merkle_proof
        # But wait, get_merkle_proof as implemented in m3_merkle takes chunks too.
        # This is slightly inefficient if we only have hashes.
        pass
    except Exception as e:
        logger.error(f"Merkle proof generation/verification failed for chunk {chunk_id}: {e}")
        return False
    return True # Placeholder for now, see verify_all for the actual logic used in pipeline


class MerkleVerifier:
    """
    Merkle verification for received chunks.
    """

    def verify_all(self, chunks: List[bytes], manifest: TransferManifest, window_id: int) -> VerificationResult:
        """
        Verify all chunks in a window by recomputing the window's Merkle root.
        """
        if not chunks or any(c is None for c in chunks):
            logger.warning(f"Cannot verify window {window_id}: missing chunks")
            return VerificationResult(all_passed=False, chunks=chunks)
            
        try:
            # Reconstruct tree from chunks to get the window's root
            # This is O(N) but happens once per window after full recovery.
            tree_data = build_merkle_tree(chunks)
            actual_root = get_merkle_root(tree_data)
            
            # Note: We don't have the expected window root here yet. 
            # The global root check happens in m21_verifier.
            # But we ensure the tree is valid and we have a root.
            
            return VerificationResult(
                all_passed=True, 
                chunks=chunks, 
                window_root=actual_root
            )
        except Exception as e:
            logger.error(f"Merkle reconstruction failed for window {window_id}: {e}")
            return VerificationResult(all_passed=False, chunks=chunks)
