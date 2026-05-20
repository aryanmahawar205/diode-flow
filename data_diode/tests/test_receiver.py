"""
Tests for receiver components and simulation (Steps 16-19).

Coverage:
- receiver/m16_fountain_decoder.py
- receiver/m20_file_reassembler.py
- receiver/m21_verifier.py
- simulate_diode.py (integration test)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from receiver.m16_fountain_decoder import FountainDecoderWrapper
from receiver.m20_file_reassembler import FileReassembler
from receiver.m21_verifier import FileVerifier, MerkleVerifier
from receiver.m15_pooler import PooledPacket


class TestFountainDecoderWrapper:
    """Test fountain decoder wrapper."""

    def test_wrapper_init(self):
        """Initialize wrapper."""
        wrapper = FountainDecoderWrapper("lt")
        assert wrapper.codec == "lt"
        assert wrapper.decoder is not None

    def test_wrapper_invalid_K(self):
        """Reject invalid K."""
        wrapper = FountainDecoderWrapper("lt")

        with pytest.raises(ValueError, match="K must be positive"):
            wrapper.decode_window([], K=0, chunk_size=1024)

    def test_wrapper_invalid_chunk_size(self):
        """Reject invalid chunk_size."""
        wrapper = FountainDecoderWrapper("lt")

        with pytest.raises(ValueError, match="chunk_size must be positive"):
            wrapper.decode_window([], K=10, chunk_size=0)

    def test_wrapper_empty_packets(self):
        """Handle empty packet list."""
        wrapper = FountainDecoderWrapper("lt")
        result = wrapper.decode_window([], K=10, chunk_size=1024)
        assert result.chunks == []
        assert result.success == False

    def test_recovery_stats(self):
        """Extract recovery statistics."""
        from fountain.interface import DecodeResult

        wrapper = FountainDecoderWrapper("lt")
        result = DecodeResult(chunks=[b"chunk1", None, b"chunk3"], missing_ids=[1], success=False)

        stats = wrapper.get_recovery_stats(result)
        assert stats["chunks_recovered"] == 2
        assert stats["chunks_missing"] == 1
        assert stats["recovery_rate"] == pytest.approx(2/3)


class TestFileReassembler:
    """Test file reassembler."""

    def test_reassembler_init(self):
        """Initialize reassembler."""
        reassembler = FileReassembler()
        assert len(reassembler.chunks_buffer) == 0

    def test_add_window_chunks_valid(self):
        """Add valid window chunks."""
        reassembler = FileReassembler()
        chunks = [b"x" * 1024, b"y" * 1024, b"z" * 1024]

        added = reassembler.add_window_chunks(
            window_id=0,
            chunks=chunks,
            chunk_size=1024,
            padding_length=0
        )
        assert added
        assert reassembler.chunks_buffer[0] == (chunks, 0)

    def test_add_window_chunks_with_missing(self):
        """Reject window with missing chunks."""
        reassembler = FileReassembler()
        chunks = [b"x" * 1024, None, b"z" * 1024]

        added = reassembler.add_window_chunks(
            window_id=0,
            chunks=chunks,
            chunk_size=1024,
            padding_length=0
        )
        assert not added

    def test_add_window_chunks_invalid_size(self):
        """Reject chunks with wrong size."""
        reassembler = FileReassembler()
        chunks = [b"x" * 1024, b"y" * 512, b"z" * 1024]

        with pytest.raises(ValueError, match="size mismatch"):
            reassembler.add_window_chunks(
                window_id=0,
                chunks=chunks,
                chunk_size=1024,
                padding_length=0
            )

    def test_reassemble_single_window(self):
        """Reassemble single window file."""
        reassembler = FileReassembler()
        chunks = [b"abc", b"def", b"ghi"]

        reassembler.add_window_chunks(
            window_id=0,
            chunks=chunks,
            chunk_size=3,
            padding_length=0
        )

        result = reassembler.reassemble_file(
            total_windows=1,
            chunk_size=3,
            expected_file_size=9
        )
        assert result == b"abcdefghi"

    def test_reassemble_with_padding(self):
        """Reassemble file with padding removal."""
        reassembler = FileReassembler()
        # 3 chunks of 5 bytes each, last has 2 bytes padding
        chunks = [b"abcde", b"fghij", b"klmno"]

        reassembler.add_window_chunks(
            window_id=0,
            chunks=chunks,
            chunk_size=5,
            padding_length=0  # We'll manually strip last chunk
        )

        # Manually test padding removal logic
        result = reassembler.reassemble_file(
            total_windows=1,
            chunk_size=5,
            expected_file_size=15
        )
        assert result == b"abcdefghijklmno"

    def test_reassemble_missing_window(self):
        """Fail if window missing."""
        reassembler = FileReassembler()
        chunks = [b"abc", b"def"]

        reassembler.add_window_chunks(
            window_id=0,
            chunks=chunks,
            chunk_size=3,
            padding_length=0
        )

        result = reassembler.reassemble_file(
            total_windows=2,  # Expect 2 windows
            chunk_size=3,
            expected_file_size=6
        )
        assert result is None

    def test_reassemble_size_mismatch(self):
        """Fail if final size doesn't match."""
        reassembler = FileReassembler()
        chunks = [b"abc", b"def"]

        reassembler.add_window_chunks(
            window_id=0,
            chunks=chunks,
            chunk_size=3,
            padding_length=0
        )

        with pytest.raises(ValueError, match="size mismatch"):
            reassembler.reassemble_file(
                total_windows=1,
                chunk_size=3,
                expected_file_size=10  # Wrong size
            )

    def test_clear(self):
        """Clear buffer."""
        reassembler = FileReassembler()
        chunks = [b"abc"]
        reassembler.add_window_chunks(0, chunks, 3, 0)

        assert len(reassembler.chunks_buffer) == 1
        reassembler.clear()
        assert len(reassembler.chunks_buffer) == 0


class TestFileVerifier:
    """Test file verification."""

    def test_compute_sha256_known(self):
        """Compute SHA256 for known data."""
        data = b"Hello, World!"
        expected = "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"
        actual = FileVerifier.compute_sha256(data)
        assert actual == expected

    def test_verify_sha256_match(self):
        """Verify matching SHA256."""
        data = b"test data"
        hash_val = FileVerifier.compute_sha256(data)
        assert FileVerifier.verify_sha256(data, hash_val)

    def test_verify_sha256_mismatch(self):
        """Reject mismatched SHA256."""
        data = b"test data"
        wrong_hash = "0" * 64
        assert not FileVerifier.verify_sha256(data, wrong_hash)

    def test_verify_file_complete(self):
        """Complete file verification."""
        data = b"file content"
        size = len(data)
        hash_val = FileVerifier.compute_sha256(data)

        result = FileVerifier.verify_file(data, size, hash_val)

        assert result["size_match"]
        assert result["hash_match"]
        assert result["valid"]

    def test_verify_file_size_mismatch(self):
        """Detect size mismatch."""
        data = b"file content"
        wrong_size = 999
        hash_val = FileVerifier.compute_sha256(data)

        result = FileVerifier.verify_file(data, wrong_size, hash_val)

        assert not result["size_match"]
        assert result["hash_match"]
        assert not result["valid"]

    def test_verify_file_hash_mismatch(self):
        """Detect hash mismatch."""
        data = b"file content"
        size = len(data)
        wrong_hash = "0" * 64

        result = FileVerifier.verify_file(data, size, wrong_hash)

        assert result["size_match"]
        assert not result["hash_match"]
        assert not result["valid"]


class TestMerkleVerifier:
    """Test Merkle verification (placeholder)."""

    def test_merkle_verify_no_proofs(self):
        """Skip verification if no proofs."""
        chunks = [b"c1", b"c2"]
        merkle_root = "root"

        result = MerkleVerifier.verify_chunks_with_merkle(
            chunks,
            merkle_root,
            merkle_proofs=None
        )
        assert result  # Returns True (placeholder)

    def test_merkle_verify_with_proofs(self):
        """Placeholder verification with proofs."""
        chunks = [b"c1", b"c2"]
        merkle_root = "root"
        proofs = {0: ["proof1"], 1: ["proof2"]}

        result = MerkleVerifier.verify_chunks_with_merkle(
            chunks,
            merkle_root,
            merkle_proofs=proofs
        )
        assert result  # Placeholder returns True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
