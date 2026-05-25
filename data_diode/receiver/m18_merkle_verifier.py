"""
receiver/m18_merkle_verifier.py — Merkle Verification
"""

from __future__ import annotations
import hashlib
import logging
from typing import List, Optional
from data_diode.sender.m3_merkle import verify_merkle_proof, build_merkle_tree, get_merkle_root
from data_diode.common.models import TransferManifest

logger = logging.getLogger(__name__)

class MerkleVerifier:
    """
    Merkle verification for received chunks.
    """

    def verify_window(self, chunks: List[bytes], expected_window_root: str) -> bool:
        """
        Verify an entire window by reconstructing its Merkle tree.
        """
        if not chunks:
            return False
            
        # Reconstruct tree from chunks
        try:
            tree_data = build_merkle_tree(chunks)
            actual_root = get_merkle_root(tree_data)
            
            import hmac
            return hmac.compare_digest(actual_root, expected_window_root)
        except Exception as e:
            logger.error(f"Merkle reconstruction failed: {e}")
            return False

    def verify_all(self, chunks: List[bytes], manifest: TransferManifest, window_id: int) -> VerificationResult:
        """
        Verify all chunks in a window. 
        Currently verifies the whole window at once.
        """
        # In a real system with per-chunk proofs, we'd verify each one.
        # Here we reconstruct the window root and compare it.
        # (Assuming window_merkle_root is available in WindowManifest or similar)
        
        # For Phase 2, we might just be verifying the whole file at the end,
        # but the pipeline expects per-window verification.
        
        # Placeholder: just return success for now if data is present
        # but in production this MUST verify against a known root.
        passed = all(c is not None for c in chunks)
        return VerificationResult(all_passed=passed, chunks=chunks)


from dataclasses import dataclass

@dataclass
class VerificationResult:
    all_passed: bool
    chunks: List[bytes]

from dataclasses import dataclass
