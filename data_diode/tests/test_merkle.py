"""
Unit tests for Merkle tree builder and verifier.

Test coverage:
- Tree construction from chunks
- Proof generation and verification
- Edge cases: single chunk, power-of-2, non-power-of-2
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from sender.m3_merkle import (
    build_merkle_tree,
    get_merkle_root,
    get_merkle_proof,
    verify_merkle_proof,
    _sha256_hash,
    _merkle_parent_hash,
    _next_power_of_2,
    MerkleTreeNode,
)


class TestMerkleHelpers:
    """Test Merkle tree helper functions."""

    def test_sha256_hash_consistency(self):
        """Same data produces same hash."""
        data = b"test_data"
        hash1 = _sha256_hash(data)
        hash2 = _sha256_hash(data)
        assert hash1 == hash2

    def test_sha256_hash_is_hex(self):
        """SHA-256 hash is 64-character hex string."""
        hash_val = _sha256_hash(b"test")
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_merkle_parent_hash(self):
        """Parent hash of two children is deterministic."""
        left = _sha256_hash(b"left")
        right = _sha256_hash(b"right")
        parent = _merkle_parent_hash(left, right)

        # Same inputs produce same parent
        parent2 = _merkle_parent_hash(left, right)
        assert parent == parent2

    def test_merkle_parent_hash_order_matters(self):
        """Order matters: parent(A, B) != parent(B, A) usually."""
        left = _sha256_hash(b"left")
        right = _sha256_hash(b"right")
        parent1 = _merkle_parent_hash(left, right)
        parent2 = _merkle_parent_hash(right, left)
        assert parent1 != parent2  # Different order → different parent

    def test_next_power_of_2(self):
        """Compute next power of 2."""
        assert _next_power_of_2(1) == 1
        assert _next_power_of_2(2) == 2
        assert _next_power_of_2(3) == 4
        assert _next_power_of_2(4) == 4
        assert _next_power_of_2(5) == 8
        assert _next_power_of_2(15) == 16
        assert _next_power_of_2(16) == 16
        assert _next_power_of_2(1000) == 1024


class TestMerkleTreeConstruction:
    """Test Merkle tree building."""

    def test_build_tree_single_chunk(self):
        """Build tree from single chunk."""
        chunks = [b"data1"]
        tree_data = build_merkle_tree(chunks)
        tree = tree_data[0]

        # Single chunk: 1 leaf (root)
        assert len(tree) >= 1
        root = get_merkle_root(tree_data)
        assert root == _sha256_hash(b"data1")

    def test_build_tree_two_chunks(self):
        """Build tree from two chunks."""
        chunks = [b"data1", b"data2"]
        tree_data = build_merkle_tree(chunks)
        tree = tree_data[0]

        # 2 leaves + 1 root = 3 nodes
        assert len(tree) >= 3
        root = get_merkle_root(tree_data)
        expected = _merkle_parent_hash(
            _sha256_hash(b"data1"),
            _sha256_hash(b"data2"),
        )
        assert root == expected

    def test_build_tree_three_chunks(self):
        """Build tree from 3 chunks (pads to 4)."""
        chunks = [b"a", b"b", b"c"]
        tree_data = build_merkle_tree(chunks)
        tree = tree_data[0]

        # 3 leaves, padded to 4
        # Leaves: a, b, c, c (duplicated)
        # Since "c" and "c" have same hash, dict has 3 unique leaves
        # Level 1: (a+b), (c+c)
        # Level 2: root
        # Total: 3 + 2 + 1 = 6 nodes (due to duplicate c)
        assert len(tree) >= 6

    def test_build_tree_power_of_2_chunks(self):
        """Build tree from power-of-2 chunks (no padding)."""
        chunks = [b"a", b"b", b"c", b"d"]
        tree_data = build_merkle_tree(chunks)
        tree = tree_data[0]

        # 4 leaves (no padding needed)
        # Level 1: 2 nodes
        # Level 2: 1 root
        # Total: 7 nodes
        assert len(tree) == 7

    def test_build_tree_empty_raises_valueerror(self):
        """Empty chunk list raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            build_merkle_tree([])

    def test_build_tree_many_chunks(self):
        """Build tree from many chunks."""
        chunks = [str(i).encode() for i in range(100)]
        tree_data = build_merkle_tree(chunks)
        tree = tree_data[0]

        # 100 chunks, padded to 128
        # Theoretical: at least 100 + 64 + 32 + 16 + 8 + 4 + 2 + 1 = 227 (approx)
        assert len(tree) >= 200

    def test_build_tree_returns_tree_dict(self):
        """Return value is tuple with first element as dict[hash -> MerkleTreeNode]."""
        tree_data = build_merkle_tree([b"data"])
        assert isinstance(tree_data, tuple)
        tree = tree_data[0]
        assert isinstance(tree, dict)
        for hash_key, node in tree.items():
            assert isinstance(node, MerkleTreeNode)
            assert node.hash == hash_key

    def test_build_tree_nodes_have_levels(self):
        """All nodes in tree have level attribute."""
        tree_data = build_merkle_tree([b"a", b"b"])
        tree = tree_data[0]
        levels = {node.level for node in tree.values()}
        # Should have level 0 (leaves) and higher levels
        assert 0 in levels
        assert max(levels) > 0


class TestMerkleProof:
    """Test proof generation and verification."""

    def test_get_proof_single_chunk(self):
        """Proof for single chunk is empty (it's the root)."""
        chunks = [b"data"]
        tree_data = build_merkle_tree(chunks)
        proof = get_merkle_proof(tree_data, 0, chunks)

        # Single chunk is the root, no proof needed
        assert len(proof) == 0

    def test_get_proof_two_chunks(self):
        """Proof for chunk in 2-chunk tree."""
        chunks = [b"a", b"b"]
        tree_data = build_merkle_tree(chunks)

        proof0 = get_merkle_proof(tree_data, 0, chunks)
        proof1 = get_merkle_proof(tree_data, 1, chunks)

        # Both should have length 1 (the sibling)
        assert len(proof0) == 1
        assert len(proof1) == 1

    def test_get_proof_four_chunks(self):
        """Proof for chunk in 4-chunk tree."""
        chunks = [b"a", b"b", b"c", b"d"]
        tree_data = build_merkle_tree(chunks)

        # Chunks 0 and 1 are siblings (same subtree)
        proof0 = get_merkle_proof(tree_data, 0, chunks)
        proof1 = get_merkle_proof(tree_data, 1, chunks)

        # Both should have length 2 (sibling + subtree root)
        assert len(proof0) == 2
        assert len(proof1) == 2

    def test_get_proof_out_of_range_raises_valueerror(self):
        """Chunk index out of range raises ValueError."""
        chunks = [b"a", b"b"]
        tree_data = build_merkle_tree(chunks)

        with pytest.raises(ValueError, match="out of range"):
            get_merkle_proof(tree_data, 10, chunks)

        with pytest.raises(ValueError, match="out of range"):
            get_merkle_proof(tree_data, -1, chunks)

    def test_verify_proof_single_chunk(self):
        """Verify proof for single chunk."""
        chunks = [b"data"]
        tree_data = build_merkle_tree(chunks)
        root = get_merkle_root(tree_data)
        proof = get_merkle_proof(tree_data, 0, chunks)
        chunk_hash = _sha256_hash(chunks[0])

        # Proof should verify against root
        assert verify_merkle_proof(chunk_hash, proof, root)

    def test_verify_proof_two_chunks(self):
        """Verify proofs for 2-chunk tree."""
        chunks = [b"a", b"b"]
        tree_data = build_merkle_tree(chunks)
        root = get_merkle_root(tree_data)

        # Verify first chunk
        proof = get_merkle_proof(tree_data, 0, chunks)
        chunk_hash = _sha256_hash(chunks[0])
        assert verify_merkle_proof(chunk_hash, proof, root)

    def test_verify_proof_four_chunks(self):
        """Verify proofs for 4-chunk tree."""
        chunks = [b"a", b"b", b"c", b"d"]
        tree_data = build_merkle_tree(chunks)
        root = get_merkle_root(tree_data)

        # Verify first chunk (leftmost)
        proof = get_merkle_proof(tree_data, 0, chunks)
        chunk_hash = _sha256_hash(chunks[0])
        assert verify_merkle_proof(chunk_hash, proof, root)

    def test_verify_proof_rejects_wrong_root(self):
        """Verify rejects proof against wrong root."""
        chunks = [b"a", b"b"]
        tree_data = build_merkle_tree(chunks)
        proof = get_merkle_proof(tree_data, 0, chunks)
        chunk_hash = _sha256_hash(chunks[0])
        wrong_root = _sha256_hash(b"wrong_root")

        assert not verify_merkle_proof(chunk_hash, proof, wrong_root)

    def test_verify_proof_rejects_corrupted_chunk(self):
        """Verify rejects proof if chunk hash is wrong."""
        chunks = [b"a", b"b"]
        tree_data = build_merkle_tree(chunks)
        root = get_merkle_root(tree_data)
        proof = get_merkle_proof(tree_data, 0, chunks)
        corrupted_hash = _sha256_hash(b"corrupted_data")

        assert not verify_merkle_proof(corrupted_hash, proof, root)


class TestMerkleIntegration:
    """Integration tests for full Merkle workflows."""

    def test_full_workflow_small_file(self):
        """Build tree, get proofs, verify chunks."""
        data = b"The quick brown fox jumps over the lazy dog"
        chunk_size = 10
        chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)]

        tree_data = build_merkle_tree(chunks)
        root = get_merkle_root(tree_data)

        # Verify first chunk
        proof = get_merkle_proof(tree_data, 0, chunks)
        chunk_hash = _sha256_hash(chunks[0])
        assert verify_merkle_proof(chunk_hash, proof, root)

    def test_full_workflow_large_chunk_count(self):
        """Build tree from many chunks."""
        chunks = [str(i).encode().ljust(16, b'0') for i in range(100)]
        tree_data = build_merkle_tree(chunks)
        root = get_merkle_root(tree_data)

        # Spot check first chunk
        proof = get_merkle_proof(tree_data, 0, chunks)
        chunk_hash = _sha256_hash(chunks[0])
        assert verify_merkle_proof(chunk_hash, proof, root)

    def test_tree_deterministic(self):
        """Same chunks always produce same root."""
        chunks = [b"a", b"b", b"c"]
        tree1_data = build_merkle_tree(chunks)
        tree2_data = build_merkle_tree(chunks)
        root1 = get_merkle_root(tree1_data)
        root2 = get_merkle_root(tree2_data)
        assert root1 == root2

    def test_different_chunks_different_root(self):
        """Different chunks produce different root."""
        tree1_data = build_merkle_tree([b"a", b"b"])
        tree2_data = build_merkle_tree([b"x", b"y"])
        root1 = get_merkle_root(tree1_data)
        root2 = get_merkle_root(tree2_data)
        assert root1 != root2
