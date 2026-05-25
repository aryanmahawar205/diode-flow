"""
Merkle tree builder for chunk verification.

This module builds a binary Merkle tree from chunk SHA-256 hashes.
"""

from __future__ import annotations

import hashlib
import logging
import hmac
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _sha256_hash(data: bytes) -> str:
    """Compute SHA-256 hash as hex string."""
    return hashlib.sha256(data).hexdigest()


def _merkle_parent_hash(left: str, right: str) -> str:
    """Compute parent hash from two child hashes."""
    combined = bytes.fromhex(left) + bytes.fromhex(right)
    return hashlib.sha256(combined).hexdigest()


def _next_power_of_2(n: int) -> int:
    """Find next power of 2 >= n."""
    if n <= 0:
        return 1
    if n & (n - 1) == 0:
        return n
    p = 1
    while p < n:
        p <<= 1
    return p


@dataclass
class MerkleProofStep:
    """One step in a Merkle proof path."""
    sibling_hash: str
    is_left: bool


@dataclass
class MerkleTreeNode:
    """Single node in Merkle tree."""
    hash: str
    left_child: str | None = None
    right_child: str | None = None
    level: int = 0


def build_merkle_tree(chunks: list[bytes]) -> tuple:
    """
    Build a Merkle tree from chunks.
    Returns (tree, child_to_parent, sibling_map, is_left_child).
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")

    # Create leaf nodes
    leaves = [_sha256_hash(c) for c in chunks]

    # Pad to power of 2
    num_leaves = len(leaves)
    padded_size = _next_power_of_2(num_leaves)
    while len(leaves) < padded_size:
        leaves.append(leaves[-1])

    tree: dict[str, MerkleTreeNode] = {}
    current_level = leaves
    level = 0

    # Add leaves to tree
    for h in current_level:
        if h not in tree:
            tree[h] = MerkleTreeNode(hash=h, level=0)

    # Build parents iteratively
    while len(current_level) > 1:
        next_level = []
        level += 1
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1]
            parent = _merkle_parent_hash(left, right)
            tree[parent] = MerkleTreeNode(
                hash=parent, left_child=left, right_child=right, level=level
            )
            next_level.append(parent)
        current_level = next_level

    # Fix A — Build reverse lookup at tree construction time
    child_to_parent = {}
    sibling_map     = {}
    is_left_child   = {}

    for node in tree.values():
        if node.left_child and node.right_child:
            child_to_parent[node.left_child]  = node.hash
            child_to_parent[node.right_child] = node.hash
            sibling_map[node.left_child]      = node.right_child
            sibling_map[node.right_child]     = node.left_child
            is_left_child[node.left_child]    = True    # this node IS the left child
            is_left_child[node.right_child]   = False   # this node IS the right child

    return tree, child_to_parent, sibling_map, is_left_child


def get_merkle_root(tree_data: tuple) -> str:
    """Get root hash from tree data."""
    tree = tree_data[0]
    max_level = -1
    root_hash = ""
    for node in tree.values():
        if node.level > max_level:
            max_level = node.level
            root_hash = node.hash
    return root_hash


def get_merkle_proof(tree_data: tuple, chunk_index: int,
                     chunks: list[bytes]) -> list[MerkleProofStep]:
    """Fix B — O(log N) proof + correct left/right ordering."""
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise ValueError(f"chunk_index {chunk_index} out of range")

    tree, child_to_parent, sibling_map, is_left_child = tree_data
    current = _sha256_hash(chunks[chunk_index])
    proof   = []

    while current in child_to_parent:
        sibling = sibling_map[current]
        # is_left_child[current] = True means WE are the left child
        # So sibling is to the RIGHT
        proof.append(MerkleProofStep(
            sibling_hash = sibling,
            is_left      = not is_left_child[current]  # sibling is left if WE are right
        ))
        current = child_to_parent[current]

    return proof   # O(log N)


def verify_merkle_proof(chunk_hash: str, proof: list[MerkleProofStep],
                        expected_root: str) -> bool:
    """Verify proof with correct left/right ordering."""
    current = chunk_hash
    for step in proof:
        if step.is_left:
            # sibling is LEFT, current is RIGHT
            combined = bytes.fromhex(step.sibling_hash) + bytes.fromhex(current)
        else:
            # current is LEFT, sibling is RIGHT
            combined = bytes.fromhex(current) + bytes.fromhex(step.sibling_hash)
        current = hashlib.sha256(combined).hexdigest()
    return hmac.compare_digest(current, expected_root)


def _build_merkle_root_from_hashes(hashes: list[str]) -> str:
    """Helper to build root from a list of hashes."""
    if not hashes:
        return ""
    
    current_level = list(hashes)
    num_leaves = len(current_level)
    padded_size = _next_power_of_2(num_leaves)
    while len(current_level) < padded_size:
        current_level.append(current_level[-1])

    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            next_level.append(_merkle_parent_hash(current_level[i], current_level[i+1]))
        current_level = next_level
    
    return current_level[0]


def compute_global_merkle_root_streaming(
    file_path  : str,
    chunk_size : int,
) -> str:
    """
    Fix C — Streaming global Merkle root (for GB-scale files)
    Compute global Merkle root by streaming through file.
    Holds only chunk hashes in RAM (32 bytes each), not chunk data.
    """
    chunk_hashes = []
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            if len(chunk) < chunk_size:
                chunk = chunk.ljust(chunk_size, b'\x00')
            chunk_hashes.append(hashlib.sha256(chunk).hexdigest())

    # Build tree from hashes only — no chunk data in RAM
    return _build_merkle_root_from_hashes(chunk_hashes)
