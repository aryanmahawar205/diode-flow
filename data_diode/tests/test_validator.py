"""
tests/test_validator.py — Tests for packet and manifest validation.
"""

import pytest
import time
from data_diode.receiver.m13_validator import PacketValidator, ManifestValidator
from data_diode.common.models import TransferManifest
from data_diode.fountain.interface import EncodedPacket

@pytest.fixture
def manifest():
    return TransferManifest(
        transfer_id="test-transfer",
        sender_node_id="sender-1",
        protocol_version="1.0.0",
        file_name="test.txt",
        file_size=1000,
        file_sha256="hash",
        chunk_size=100,
        total_chunks=10,
        rs_n=16,
        rs_k=10,
        num_passes=1,
        overhead_ratio=0.1,
        interleave_depth=2,
        window_size_bytes=1000,
        total_windows=1,
        merkle_root="root",
        mime_type="text/plain",
        creation_timestamp=time.time(),
        classification_level="standard",
        expiration_policy=3600,
        ed25519_signature=b""
    )

def test_validate_packet_valid(manifest):
    validator = PacketValidator()
    packet = EncodedPacket(
        packet_id=1,
        pass_id=0,
        seed=123,
        degree=2,
        chunk_ids=[0, 1],
        data=b"x" * 100,
        source_chunk_count=10
    )
    # Add window_id which is needed by validator but not in EncodedPacket dataclass 
    # (wait, I removed it from EncodedPacket!)
    # I should check how validator uses it.
    packet.window_id = 0 
    
    result = validator.validate_packet(packet, manifest)
    assert result.valid is True

def test_validate_packet_invalid_window(manifest):
    validator = PacketValidator()
    packet = EncodedPacket(
        packet_id=1, pass_id=0, seed=123, degree=2, chunk_ids=[0, 1],
        data=b"x" * 100, source_chunk_count=10
    )
    packet.window_id = 5 # Out of range
    
    result = validator.validate_packet(packet, manifest)
    assert result.valid is False
    assert "window_id" in result.reason

def test_manifest_hard_limits():
    validator = ManifestValidator()
    m = TransferManifest(
        transfer_id="id", sender_node_id="s", protocol_version="v",
        file_name="f", file_size=200 * 1024**3, # 200GB > 100GB
        file_sha256="h", chunk_size=100, total_chunks=10,
        rs_n=16, rs_k=10, num_passes=1, overhead_ratio=0.1,
        interleave_depth=2, window_size_bytes=1000, total_windows=1,
        merkle_root="r", mime_type="t", creation_timestamp=time.time(),
        classification_level="s", expiration_policy=3600, ed25519_signature=b""
    )
    result = validator.validate_manifest_hard_limits(m)
    assert result.valid is False
    assert "file_size" in result.reason

def test_validate_timestamp():
    validator = ManifestValidator()
    start = time.time()
    
    # Valid
    assert validator.validate_timestamp(start, start).valid is True
    
    # Old
    assert validator.validate_timestamp(start - 100, start).valid is False
    
    # Future
    assert validator.validate_timestamp(start + 5000, start).valid is False
