"""
Binary Merkle tree from chunk SHA-256 hashes.
Provides O(log N) proof generation via reverse lookup dict.
verify_merkle_proof() uses correct left/right ordering.
Streaming global root computation for GB-scale files.
"""
from __future__ import annotations
import hashlib
import hmac
import logging
from dataclasses import dataclass
from common.models import MerkleProofStep

logger = logging.getLogger(__name__)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _parent(left: str, right: str) -> str:
    return hashlib.sha256(bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()

def _next_pow2(n: int) -> int:
    p = 1
    while p < n: p <<= 1
    return p


@dataclass
class MerkleTree:
    root            : str
    leaves          : list[str]          # sha256 of each chunk
    child_to_parent : dict[str, str]
    sibling         : dict[str, str]
    is_left         : dict[str, bool]    # True = this node is left child


def build_tree(chunks: list[bytes]) -> MerkleTree:
    if not chunks:
        raise ValueError("chunks cannot be empty")

    leaves_raw = [_sha256(c) for c in chunks]
    padded     = list(leaves_raw)
    target     = _next_pow2(len(padded))
    while len(padded) < target:
        padded.append(padded[-1])

    child_to_parent: dict[str, str] = {}
    sibling        : dict[str, str] = {}
    is_left        : dict[str, bool] = {}

    current = padded
    while len(current) > 1:
        next_level = []
        for i in range(0, len(current), 2):
            l, r   = current[i], current[i + 1]
            parent = _parent(l, r)
            child_to_parent[l] = parent
            child_to_parent[r] = parent
            sibling[l], sibling[r] = r, l
            is_left[l], is_left[r] = True, False
            next_level.append(parent)
        current = next_level

    root = current[0]
    return MerkleTree(root=root, leaves=leaves_raw,
                      child_to_parent=child_to_parent,
                      sibling=sibling, is_left=is_left)


def get_proof(tree: MerkleTree, chunk_index: int) -> list[MerkleProofStep]:
    """O(log N) — uses reverse lookup, not full tree scan."""
    current = tree.leaves[chunk_index]
    proof   = []
    while current in tree.child_to_parent:
        sib = tree.sibling[current]
        # is_left[current]=True means WE are left → sibling is RIGHT
        # Proof step records whether SIBLING is left
        proof.append(MerkleProofStep(sibling_hash=sib,
                                     is_left=not tree.is_left[current]))
        current = tree.child_to_parent[current]
    return proof


def verify_proof(chunk_hash: str, proof: list[MerkleProofStep],
                 expected_root: str) -> bool:
    current = chunk_hash
    for step in proof:
        if step.is_left:
            combined = bytes.fromhex(step.sibling_hash) + bytes.fromhex(current)
        else:
            combined = bytes.fromhex(current) + bytes.fromhex(step.sibling_hash)
        current = hashlib.sha256(combined).hexdigest()
    return hmac.compare_digest(current, expected_root)


def global_root_streaming(file_path: str, chunk_size: int) -> str:
    """
    Compute global Merkle root by streaming file.
    Holds only hashes in RAM (32 bytes each).
    Safe for 10GB files: 8.7M chunks × 32 bytes = 278MB.
    """
    hashes = []
    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            if len(chunk) < chunk_size:
                chunk = chunk.ljust(chunk_size, b'\x00')
            hashes.append(_sha256(chunk))

    # Build tree from hashes (not raw chunk data)
    leaves = list(hashes)
    target = _next_pow2(len(leaves))
    while len(leaves) < target:
        leaves.append(leaves[-1])

    current = leaves
    while len(current) > 1:
        current = [_parent(current[i], current[i+1])
                   for i in range(0, len(current), 2)]
    return current[0]
