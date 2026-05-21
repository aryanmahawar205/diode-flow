"""
Unit tests for common models and sender chunker.

Test coverage:
- Dataclass creation and validation
- Config constants and profile lookup
- Chunker: edge cases, padding, validation
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from data_diode.common.models import (
    TransferManifest,
    WindowManifest,
    EncodedPacketMetadata,
    Chunk,
    MerkleProof,
    MerkleTree,
    TransferProfile,
    WindowDecodeSession,
    TransferDecodeSession,
    LossScenario,
)
from data_diode.common.config import (
    get_profile,
    compute_chunk_count,
    compute_window_count,
    DEFAULT_CHUNK_SIZE,
    MAX_CHUNKS_PER_WINDOW,
    PROFILES,
)
from data_diode.sender.m2_chunker import chunk_window, analyze_file, ChunkerResult


class TestModels:
    """Test dataclass creation and basic validation."""

    def test_transfer_manifest_creation(self):
        """Create TransferManifest with all fields."""
        manifest = TransferManifest(
            transfer_id="test-123",
            sender_node_id="sender-1",
            protocol_version="1.0.0",
            file_name="data.bin",
            file_size=1024,
            file_sha256="abc123",
            chunk_size=256,
            total_chunks=4,
            rs_n=8,
            rs_k=2,
            num_passes=1,
            overhead_ratio=0.5,
            interleave_depth=2,
            window_size_bytes=65536,
            total_windows=1,
            merkle_root="root123",
            mime_type="application/octet-stream",
            creation_timestamp=1000.0,
            classification_level="standard",
            expiration_policy=3600,
            ed25519_signature=b"sig",
        )
        assert manifest.transfer_id == "test-123"
        assert manifest.file_size == 1024
        assert manifest.total_chunks == 4

    def test_window_manifest_creation(self):
        """Create WindowManifest."""
        window = WindowManifest(
            transfer_id="test",
            window_id=0,
            window_offset=0,
            window_size=65536,
            chunk_count=256,
            chunk_count_with_rs=260,
            padding_length=0,
            window_merkle_root="root",
        )
        assert window.window_id == 0
        assert window.chunk_count == 256

    def test_chunk_creation(self):
        """Create Chunk with metadata."""
        chunk = Chunk(
            chunk_id=0,
            data=b"data" * 100,
            window_id=0,
            chunk_sha256="abc123",
            is_verified=False,
        )
        assert chunk.chunk_id == 0
        assert len(chunk.data) == 400

    def test_transfer_profile_creation(self):
        """Create TransferProfile."""
        profile = TransferProfile(
            num_passes=2,
            overhead_ratio=0.15,
            rs_n=32,
            rs_k=4,
            interleave_depth=4,
            header_redundancy=3,
            window_size_bytes=64 * 1024 * 1024,
        )
        assert profile.num_passes == 2
        assert profile.rs_n == 32

    def test_loss_scenario_creation(self):
        """Create LossScenario."""
        scenario = LossScenario(
            name="10% random",
            random_loss_rate=0.10,
        )
        assert scenario.name == "10% random"
        assert scenario.random_loss_rate == 0.10


class TestConfig:
    """Test configuration constants and helper functions."""

    def test_get_profile_small_standard(self):
        """Get profile for small standard file."""
        profile = get_profile(1_000_000, "standard")
        assert profile.num_passes >= 1
        assert profile.rs_k >= 2

    def test_get_profile_medium_critical(self):
        """Get profile for medium critical file."""
        profile = get_profile(100_000_000, "critical")
        assert profile.num_passes >= 2
        assert profile.rs_k >= 4

    def test_get_profile_large_classified(self):
        """Get profile for large classified file."""
        profile = get_profile(1_000_000_000, "classified")
        assert profile.num_passes >= 3
        assert profile.rs_k >= 8

    def test_get_profile_invalid_criticality_raises_valueerror(self):
        """Invalid criticality raises ValueError."""
        with pytest.raises(ValueError, match="criticality must be one of"):
            get_profile(1_000_000, "invalid")

    def test_compute_chunk_count(self):
        """Compute chunks needed for given size and chunk_size."""
        # 1000 bytes with 256-byte chunks = 4 chunks
        count = compute_chunk_count(1000, 256)
        assert count == 4

    def test_compute_chunk_count_exact_fit(self):
        """Chunks that fit exactly don't need padding."""
        count = compute_chunk_count(1024, 256)
        assert count == 4

    def test_compute_chunk_count_single_chunk(self):
        """Single byte requires 1 chunk."""
        count = compute_chunk_count(1, 256)
        assert count == 1

    def test_compute_window_count(self):
        """Compute windows needed for given file size."""
        # 1 GB file with 64 MB windows = 16 windows
        count = compute_window_count(1024**3, 64 * 1024 * 1024)
        assert count == 16

    def test_compute_window_count_single_window(self):
        """Small file in single window."""
        count = compute_window_count(1_000_000, 64 * 1024 * 1024)
        assert count == 1

    def test_profile_table_completeness(self):
        """All size/criticality combos have profiles."""
        for size_cat in ["small", "medium", "large"]:
            for crit in ["standard", "critical", "classified"]:
                assert (size_cat, crit) in PROFILES


class TestChunker:
    """Test file chunking operations."""

    def test_chunk_window_basic(self):
        """Chunk simple window."""
        result = chunk_window(b"hello", chunk_size=3)
        assert result.chunk_count == 2
        assert len(result.chunks) == 2
        assert all(len(c) == 3 for c in result.chunks)
        assert result.chunks[0] == b"hel"
        assert result.chunks[1] == b"lo\x00"

    def test_chunk_window_exact_fit(self):
        """Window that chunks exactly needs no padding."""
        result = chunk_window(b"hello world", chunk_size=11)
        assert result.chunk_count == 1
        assert result.padding_length == 0
        assert result.chunks[0] == b"hello world"

    def test_chunk_window_single_chunk(self):
        """Single byte becomes padded chunk."""
        result = chunk_window(b"a", chunk_size=5)
        assert result.chunk_count == 1
        assert result.padding_length == 4
        assert result.chunks[0] == b"a\x00\x00\x00\x00"

    def test_chunk_window_multiple_chunks(self):
        """Multiple chunks with padding in last."""
        result = chunk_window(b"abcdefghij", chunk_size=3)
        assert result.chunk_count == 4
        assert result.chunks[0] == b"abc"
        assert result.chunks[1] == b"def"
        assert result.chunks[2] == b"ghi"
        assert result.chunks[3] == b"j\x00\x00"
        assert result.padding_length == 2

    def test_chunk_window_preserves_data(self):
        """Chunking preserves all data (minus padding)."""
        data = b"The quick brown fox jumps over the lazy dog" * 10
        result = chunk_window(data, chunk_size=64)

        # Concatenate chunks minus padding from last
        recovered = b"".join(result.chunks[:-1])
        recovered += result.chunks[-1][:-result.padding_length] if result.padding_length > 0 else result.chunks[-1]

        assert recovered == data

    def test_chunk_window_empty_raises_valueerror(self):
        """Empty window raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            chunk_window(b"", chunk_size=10)

    def test_chunk_window_zero_chunk_size_raises_valueerror(self):
        """chunk_size <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            chunk_window(b"data", chunk_size=0)

    def test_chunk_window_negative_chunk_size_raises_valueerror(self):
        """Negative chunk_size raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            chunk_window(b"data", chunk_size=-1)

    def test_chunk_window_huge_chunk_size_raises_valueerror(self):
        """Chunk size exceeds safety limit."""
        with pytest.raises(ValueError, match="too large"):
            chunk_window(b"data", chunk_size=2 * 1024 * 1024)

    def test_chunk_window_all_chunks_equal_size(self):
        """All chunks have exactly chunk_size."""
        for data_size in [1, 10, 100, 1000]:
            for chunk_size in [3, 7, 16, 64]:
                result = chunk_window(b"x" * data_size, chunk_size=chunk_size)
                for i, chunk in enumerate(result.chunks):
                    assert len(chunk) == chunk_size, \
                        f"Chunk {i} size {len(chunk)} != {chunk_size}"

    def test_chunk_window_result_fields(self):
        """ChunkerResult has all expected fields."""
        result = chunk_window(b"test_data", chunk_size=4)
        assert hasattr(result, "chunks")
        assert hasattr(result, "chunk_count")
        assert hasattr(result, "padding_length")
        assert hasattr(result, "original_window_size")
        assert result.chunk_count == len(result.chunks)


class TestChunkerIntegration:
    """Integration tests for config + chunker."""

    def test_chunking_with_default_chunk_size(self):
        """Chunk file with default size."""
        result = chunk_window(b"x" * 10000, chunk_size=DEFAULT_CHUNK_SIZE)
        assert result.chunk_count > 0
        assert all(len(c) == DEFAULT_CHUNK_SIZE for c in result.chunks)

    def test_chunking_small_file_various_sizes(self):
        """Chunk small file with various chunk sizes."""
        data = b"small file content" * 5
        for chunk_size in [8, 16, 32, 64, 128]:
            result = chunk_window(data, chunk_size=chunk_size)
            assert result.chunk_count > 0
            # Verify we can recover original (minus padding)
            recovered_size = result.chunk_count * chunk_size - result.padding_length
            assert recovered_size == len(data)

    def test_profile_window_size_chunks_consistency(self):
        """Profile window size produces reasonable chunk count."""
        profile = get_profile(10_000_000, "standard")
        chunk_count = compute_chunk_count(profile.window_size_bytes, DEFAULT_CHUNK_SIZE)
        assert chunk_count <= MAX_CHUNKS_PER_WINDOW
