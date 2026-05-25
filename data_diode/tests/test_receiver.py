"""
Tests for receiver components.

Coverage:
- receiver/m16_fountain_decoder.py
- receiver/m20_file_reassembler.py
- receiver/m21_verifier.py
"""

import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from receiver.m16_fountain_decoder import FountainDecoderWrapper
from receiver.m20_file_reassembler import FileReassembler
from receiver.m21_verifier import FileVerifier
from receiver.m18_merkle_verifier import MerkleVerifier
from common.models import TransferManifest


class TestFountainDecoderWrapper:
    """Test fountain decoder wrapper."""

    def test_wrapper_init(self):
        """Initialize wrapper."""
        wrapper = FountainDecoderWrapper("lt")
        assert wrapper.codec == "lt"
        assert wrapper.decoder is not None


class TestFileReassembler:
    """Test file reassembler (disk-based)."""

    def test_assemble_window_data(self):
        """Test basic chunk assembly."""
        reassembler = FileReassembler()
        chunks = [b"abc", b"def", b"ghi"]
        data = reassembler.assemble_window_data(chunks)
        assert data == b"abcdefghi"

    def test_assemble_window_data_with_padding(self):
        """Test chunk assembly with padding removal."""
        reassembler = FileReassembler()
        chunks = [b"abc", b"def", b"gh\x00"]
        data = reassembler.assemble_window_data(chunks, padding_length=1)
        assert data == b"abcdefgh"

    def test_streaming_assemble(self):
        """Test concatenating window files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            w1 = tmpdir_path / "w1.part"
            w2 = tmpdir_path / "w2.part"
            w1.write_bytes(b"window1data")
            w2.write_bytes(b"window2data")
            
            output = tmpdir_path / "final.bin"
            expected_data = b"window1data" + b"window2data"
            import hashlib
            expected_sha256 = hashlib.sha256(expected_data).hexdigest()
            
            reassembler = FileReassembler()
            success = reassembler.streaming_assemble(
                window_files={0: w1, 1: w2},
                total_windows=2,
                output_path=output,
                expected_sha256=expected_sha256
            )
            
            assert success is True
            assert output.read_bytes() == expected_data
            assert not w1.exists()
            assert not w2.exists()


class TestFileVerifier:
    """Test file verification (streaming)."""

    def test_verify_sha256_streaming(self):
        """Verify SHA256 of file on disk."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            data = b"hello streaming world"
            tmp.write(data)
            tmp_path = tmp.name
        
        try:
            import hashlib
            expected = hashlib.sha256(data).hexdigest()
            assert FileVerifier.verify_sha256_streaming(tmp_path, expected) is True
            assert FileVerifier.verify_sha256_streaming(tmp_path, "wrong") is False
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestMerkleVerifier:
    """Test Merkle verification."""

    def test_verify_all_success(self):
        """Verify window by recomputing root."""
        chunks = [b"c1", b"c2"]
        from sender.m3_merkle import build_merkle_tree, get_merkle_root
        tree = build_merkle_tree(chunks)
        root = get_merkle_root(tree)
        
        verifier = MerkleVerifier()
        # TransferManifest is needed for the signature but not used in verify_all logic currently
        manifest = None 
        
        result = verifier.verify_all(chunks, manifest, 0)
        assert result.all_passed is True
        assert result.window_root == root
