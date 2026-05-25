"""
sender/m3_merkle.py — Optimized Merkle Tree Builder
"""

from __future__ import annotations

import hashlib
import logging
import hmac
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _sha256_bytes(data: bytes) -> bytes:
    """Compute SHA-256 hash as raw bytes."""
    return hashlib.sha256(data).digest()


def _merkle_parent_hash(left: bytes, right: bytes) -> bytes:
    """Compute parent hash from two child hashes (raw bytes)."""
    return hashlib.sha256(left + right).digest()


def _next_power_of_2(n: int) -> int:
    """Find next power of 2 >= n."""
    if n <= 0: return 1
    if n & (n - 1) == 0: return n
    p = 1
    while p < n: p <<= 1
    return p


@dataclass
class MerkleProofStep:
    """One step in a Merkle proof path."""
    sibling_hash: bytes
    is_left: bool


@dataclass
class MerkleTreeNode:
    """Single node in Merkle tree."""
    hash: bytes
    left_child: bytes | None = None
    right_child: bytes | None = None
    level: int = 0


def build_merkle_tree(chunks: list[bytes]) -> tuple:
    """
    Build a Merkle tree from chunks.
    Returns (tree_dict, child_to_parent, sibling_map, is_left_child).
    Everything uses raw bytes for speed.
    """
    if not chunks: raise ValueError("chunks list cannot be empty")

    leaves = [_sha256_bytes(c) for c in chunks]
    num_leaves = len(leaves)
    padded_size = _next_power_of_2(num_leaves)
    while len(leaves) < padded_size:
        leaves.append(leaves[-1])

    tree: dict[bytes, MerkleTreeNode] = {}
    current_level = leaves
    level = 0

    for h in current_level:
        if h not in tree:
            tree[h] = MerkleTreeNode(hash=h, level=0)

    while len(current_level) > 1:
        next_level = []
        level += 1
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1]
            parent = _merkle_parent_hash(left, right)
            tree[parent] = MerkleTreeNode(hash=parent, left_child=left, right_child=right, level=level)
            next_level.append(parent)
        current_level = next_level

    child_to_parent, sibling_map, is_left_child = {}, {}, {}
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
    """Get root hash as hex string."""
    tree = tree_data[0]
    max_level = -1
    root_bytes = b""
    for node in tree.values():
        if node.level > max_level:
            max_level = node.level
            root_bytes = node.hash
    return root_bytes.hex()


def get_merkle_proof(tree_data: tuple, chunk_index: int, chunks: list[bytes]) -> list[MerkleProofStep]:
    tree, child_to_parent, sibling_map, is_left_child = tree_data
    current = _sha256_bytes(chunks[chunk_index])
    proof = []
    while current in child_to_parent:
        sibling = sibling_map[current]
        proof.append(MerkleProofStep(sibling_hash=sibling, is_left=not is_left_child[current]))
        current = child_to_parent[current]
    return proof


def verify_merkle_proof(chunk_hash: str, proof: list[MerkleProofStep], expected_root: str) -> bool:
    current = bytes.fromhex(chunk_hash)
    for step in proof:
        if step.is_left: current = hashlib.sha256(step.sibling_hash + current).digest()
        else:           current = hashlib.sha256(current + step.sibling_hash).digest()
    return hmac.compare_digest(current.hex(), expected_root)


def compute_merkle_root_from_hashes(hashes: list[str]) -> str:
    """Build root from a list of hex hashes."""
    if not hashes: return ""
    current_level = [bytes.fromhex(h) for h in hashes]
    num_leaves = len(current_level)
    padded_size = _next_power_of_2(num_leaves)
    while len(current_level) < padded_size:
        current_level.append(current_level[-1])

    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            next_level.append(_merkle_parent_hash(current_level[i], current_level[i+1]))
        current_level = next_level
    return current_level[0].hex()


def compute_merkle_root_from_chunks(chunks: list[bytes]) -> str:
    """Fast root computation without building the whole tree object."""
    if not chunks: return ""
    current_level = [_sha256_bytes(c) for c in chunks]
    num_leaves = len(current_level)
    padded_size = _next_power_of_2(num_leaves)
    while len(current_level) < padded_size:
        current_level.append(current_level[-1])
    
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            next_level.append(_merkle_parent_hash(current_level[i], current_level[i+1]))
        current_level = next_level
    return current_level[0].hex()


def compute_global_merkle_root_streaming(file_path: str, chunk_size: int) -> str:
    """Streaming global Merkle root for large files."""
    chunk_hashes = []
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk: break
            if len(chunk) < chunk_size:
                chunk = chunk.ljust(chunk_size, b'\x00')
            chunk_hashes.append(hashlib.sha256(chunk).digest())

    if not chunk_hashes: return ""
    current_level = chunk_hashes
    padded_size = _next_power_of_2(len(current_level))
    while len(current_level) < padded_size:
        current_level.append(current_level[-1])

    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            next_level.append(_merkle_parent_hash(current_level[i], current_level[i+1]))
        current_level = next_level
    return current_level[0].hex()
