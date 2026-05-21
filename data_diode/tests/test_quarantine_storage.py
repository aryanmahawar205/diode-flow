"""
Tests for quarantine and secure storage modules.
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.models import TransferManifest
from receiver.m22_quarantine import QuarantineManager
from receiver.m23_storage import StorageWriter


def make_manifest() -> TransferManifest:
    return TransferManifest(
        transfer_id="test-transfer",
        sender_node_id="sender-1",
        protocol_version="1.0.0",
        file_name="file.bin",
        file_size=9,
        file_sha256="abc123",
        chunk_size=3,
        total_chunks=3,
        rs_n=8,
        rs_k=2,
        num_passes=1,
        overhead_ratio=0.2,
        interleave_depth=2,
        window_size_bytes=1024,
        total_windows=1,
        merkle_root="deadbeef",
        mime_type="application/octet-stream",
        creation_timestamp=time.time(),
        classification_level="standard",
        expiration_policy=3600,
        ed25519_signature=b"sig",
    )


def test_quarantine_accepts_matching_size():
    """Quarantine should accept files that match manifest size."""
    manifest = make_manifest()
    manager = QuarantineManager(quarantine_dir=tempfile.mkdtemp())
    result = manager.inspect_policy(b"123456789", manifest)

    assert result.accepted
    assert result.reason == "accepted"


def test_quarantine_rejects_size_mismatch():
    """Quarantine should reject mismatched size."""
    manifest = make_manifest()
    manager = QuarantineManager(quarantine_dir=tempfile.mkdtemp())
    result = manager.inspect_policy(b"1234", manifest)

    assert not result.accepted
    assert result.reason == "file_size_mismatch"


def test_storage_writer_creates_receipt(tmp_path: Path):
    """Storage writer should store file and write receipt."""
    writer = StorageWriter(storage_dir=str(tmp_path), permissions=0o700)
    manifest = make_manifest()
    data = b"123456789"

    path = writer.store_file(data, manifest, packets_received=10, packets_dropped=2)
    assert path.endswith("test-transfer_file.bin")
    assert Path(path).exists()
    assert Path(path + ".receipt.json").exists()
