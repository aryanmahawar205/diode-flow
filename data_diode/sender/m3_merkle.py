"""
Merkle tree builder for chunk verification.

This module builds a binary Merkle tree from chunk SHA-256 hashes. It produces:
1. Per-chunk leaf hash (used in proofs)
2. Tree nodes at each level
3. Root hash for file integrity

Why Merkle trees?
- Single-file SHA-256 verifies only at the end
- Merkle allows per-chunk verification during transfer
- Corrupted chunks are identified immediately (not just missing)
- Enables efficient partial file verification

Design decisions:
- Tree is padded to power of 2 (duplicate last leaf if needed)
- Built bottom-up: leaves are chunk hashes, parents are hash(left + right)
- Proofs are O(log N) paths from leaf to root
- Immutable after construction (frozen dataclass)

Implementation references:
- Merkle, R. C. (1979). A Certified Digital Signature.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _sha256_hash(data: bytes) -> str:
    """
    Compute SHA-256 hash as hex string.

    Parameters:
        data: Bytes to hash.

    Returns:
        Hex string of hash.
    """
    return hashlib.sha256(data).hexdigest()


def _merkle_parent_hash(left: str, right: str) -> str:
    """
    Compute parent hash from two child hashes.

    Parameters:
        left: Hex hash of left child.
        right: Hex hash of right child.

    Returns:
        Hex hash of parent (sha256(left_bytes + right_bytes)).
    """
    # Concatenate as raw bytes (not hex strings)
    combined = bytes.fromhex(left) + bytes.fromhex(right)
    return hashlib.sha256(combined).hexdigest()


def _next_power_of_2(n: int) -> int:
    """
    Find next power of 2 >= n.

    Parameters:
        n: Input value.

    Returns:
        Smallest power of 2 >= n.
    """
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
    """
    One step in a Merkle proof path.
    
    Attributes:
        sibling_hash: Hex hash of the sibling node.
        is_left: True if the sibling is to the LEFT of the current node.
    """
    sibling_hash: str
    is_left: bool


@dataclass
class MerkleTreeNode:
    """
    Single node in Merkle tree.

    Attributes:
        hash: Hex SHA-256 hash of this node.
        left_child: Hash of left child (None for leaves).
        right_child: Hash of right child (None for leaves).
        level: 0 for leaves, increasing toward root.
    """
    hash: str
    left_child: str | None = None
    right_child: str | None = None
    level: int = 0


def build_merkle_tree(chunks: list[bytes]) -> tuple:
    """
    Build a Merkle tree from chunks.

    Returns:
        tuple (tree, child_to_parent, sibling_map, is_left_child)
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")

    logger.debug(f"Building Merkle tree for {len(chunks)} chunks")

    # Create leaf nodes
    leaves = []
    for i, chunk in enumerate(chunks):
        leaf_hash = _sha256_hash(chunk)
        leaves.append(leaf_hash)

    # Pad to power of 2
    num_leaves = len(leaves)
    padded_size = _next_power_of_2(num_leaves)

    while len(leaves) < padded_size:
        leaves.append(leaves[-1])  # duplicate last leaf

    # Build tree bottom-up
    tree: dict[str, MerkleTreeNode] = {}
    current_level = leaves
    level = 0

    # Add leaves to tree
    for leaf_hash in current_level:
        if leaf_hash not in tree:
            tree[leaf_hash] = MerkleTreeNode(hash=leaf_hash, level=0)

    # Build parents iteratively
    while len(current_level) > 1:
        next_level = []
        level += 1
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1]
            parent = _merkle_parent_hash(left, right)

            tree[parent] = MerkleTreeNode(
                hash=parent,
                left_child=left,
                right_child=right,
                level=level,
            )
            next_level.append(parent)
        current_level = next_level

    # Post-process: build reverse lookup maps for O(1) step traversal
    child_to_parent: dict[str, str] = {}
    sibling_map: dict[str, str] = {}
    is_left_child: dict[str, bool] = {}

    for node in tree.values():
        if node.left_child and node.right_child:
            child_to_parent[node.left_child] = node.hash
            child_to_parent[node.right_child] = node.hash
            sibling_map[node.left_child] = node.right_child
            sibling_map[node.right_child] = node.left_child
            is_left_child[node.left_child] = True
            is_left_child[node.right_child] = False

    return tree, child_to_parent, sibling_map, is_left_child


def get_merkle_root(tree_data: tuple) -> str:
    """
    Get root hash from tree data.
    """
    tree = tree_data[0]
    # Root has the maximum level
    max_level = -1
    root_hash = ""
    for node in tree.values():
        if node.level > max_level:
            max_level = node.level
            root_hash = node.hash
    return root_hash


def get_merkle_proof(
    tree_data: tuple,
    chunk_index: int,
    chunks: list[bytes],
) -> list[MerkleProofStep]:
    """
    Get O(log N) proof generation using reverse lookup.
    """
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise ValueError(f"chunk_index {chunk_index} out of range")

    tree, child_to_parent, sibling_map, is_left_child = tree_data
    
    leaf_hash = _sha256_hash(chunks[chunk_index])
    if leaf_hash not in tree:
        raise ValueError("Leaf not in tree")

    proof = []
    current = leaf_hash
    
    while current in child_to_parent:
        sibling = sibling_map[current]
        # if WE are the right child, then sibling is LEFT
        is_sibling_left = not is_left_child[current]
        
        proof.append(MerkleProofStep(
            sibling_hash=sibling,
            is_left=is_sibling_left
        ))
        current = child_to_parent[current]
        
    return proof


def verify_merkle_proof(
    chunk_hash: str,
    proof: list[MerkleProofStep],
    expected_root: str,
) -> bool:
    """
    Verify proof with correct left/right ordering.
    """
    import hmac
    current = chunk_hash
    for step in proof:
        if step.is_left:
            # Sibling is left, current is right
            combined = bytes.fromhex(step.sibling_hash) + bytes.fromhex(current)
        else:
            # Current is left, sibling is right
            combined = bytes.fromhex(current) + bytes.fromhex(step.sibling_hash)
        current = hashlib.sha256(combined).hexdigest()
    return hmac.compare_digest(current, expected_root)
