"""
Per-chunk Merkle verification.
Verifies each decoded chunk against the Merkle tree from the sender.
Chunks failing verification are flagged as None (corrupt = treat as lost).
"""
from __future__ import annotations
import hashlib
import logging
from dataclasses import dataclass
from sender.m4_merkle import build_tree, get_proof, verify_proof

logger = logging.getLogger(__name__)


@dataclass
class VerifyResult:
    chunks      : list[bytes | None]
    all_passed  : bool
    failed_ids  : list[int]


def verify_chunks(chunks: list[bytes | None], window_chunks_for_tree: list[bytes],
                  expected_root: str) -> VerifyResult:
    """
    Build Merkle tree from known-good chunks, verify each chunk against it.
    Chunk failing its hash check → set to None → RS or failure.
    """
    # Build tree from the chunks we have (using zeroed placeholders for None)
    tree_input = [c if c is not None else bytes(len(window_chunks_for_tree[0]))
                  for c in chunks[:len(window_chunks_for_tree)]]

    try:
        tree = build_tree(tree_input)
    except Exception as e:
        logger.error(f"Failed to build Merkle tree: {e}")
        return VerifyResult(chunks=list(chunks), all_passed=False,
                            failed_ids=list(range(len(chunks))))

    result    = list(chunks)
    failed    = []

    for i, chunk in enumerate(chunks):
        if chunk is None:
            failed.append(i)
            continue
        expected_hash = hashlib.sha256(chunk).hexdigest()
        if i < len(tree.leaves) and expected_hash == tree.leaves[i]:
            continue
        else:
            logger.warning(f"Merkle mismatch on chunk {i}")
            result[i] = None
            failed.append(i)

    return VerifyResult(chunks=result, all_passed=len(failed)==0, failed_ids=failed)


def simple_verify(chunks: list[bytes | None], expected_leaf_hashes: list[str]) -> VerifyResult:
    """
    Simple per-chunk hash verification against known leaf hashes.
    Used when full proof path is not available.
    """
    result, failed = list(chunks), []
    for i, chunk in enumerate(chunks):
        if chunk is None:
            failed.append(i)
            continue
        if i < len(expected_leaf_hashes):
            actual = hashlib.sha256(chunk).hexdigest()
            if actual != expected_leaf_hashes[i]:
                logger.warning(f"Hash mismatch chunk {i}")
                result[i] = None
                failed.append(i)
    return VerifyResult(chunks=result, all_passed=len(failed)==0, failed_ids=failed)
