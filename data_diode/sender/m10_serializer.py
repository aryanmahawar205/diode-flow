"""
Manual serialization and deserialization layer for transfer data.

This module provides serialize/deserialize functions for manifests and packets.
Rather than relying on external protobuf compiler, uses Python dataclass
serialization to JSON/bytes for Phase 1.

Why manual instead of protobuf?
- No external compiler dependency
- Phase 1 goal is end-to-end proof-of-concept, not production protobuf
- Phase 2+ can migrate to actual Protobuf when protoc is available
- Manual serialization makes debugging easier

Design decisions:
- Manifest: JSON over bytes (human-readable during debugging)
- Packets: Custom binary format (compact, efficient)
- Version field allows future format upgrades
- CRC32 prevents accidental corruption
"""

from __future__ import annotations

import json
import logging
import struct
from io import BytesIO

from common.models import (
    TransferManifest,
    WindowManifest,
    EncodedPacketMetadata,
)

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1
PACKET_VERSION = 1


def serialize_manifest(manifest: TransferManifest) -> bytes:
    """
    Serialize a TransferManifest to bytes.

    Parameters:
        manifest: TransferManifest to serialize.

    Returns:
        Bytes containing serialized manifest.

    Format:
    - 1 byte: version
    - 4 bytes: payload length (big-endian)
    - N bytes: JSON payload
    - 4 bytes: CRC32C checksum
    """
    # Convert manifest to JSON
    manifest_dict = {
        "transfer_id": manifest.transfer_id,
        "sender_node_id": manifest.sender_node_id,
        "protocol_version": manifest.protocol_version,
        "file_name": manifest.file_name,
        "file_size": manifest.file_size,
        "file_sha256": manifest.file_sha256,
        "chunk_size": manifest.chunk_size,
        "total_chunks": manifest.total_chunks,
        "rs_n": manifest.rs_n,
        "rs_k": manifest.rs_k,
        "num_passes": manifest.num_passes,
        "overhead_ratio": manifest.overhead_ratio,
        "interleave_depth": manifest.interleave_depth,
        "window_size_bytes": manifest.window_size_bytes,
        "total_windows": manifest.total_windows,
        "merkle_root": manifest.merkle_root,
        "mime_type": manifest.mime_type,
        "creation_timestamp": manifest.creation_timestamp,
        "classification_level": manifest.classification_level,
        "expiration_policy": manifest.expiration_policy,
        "ed25519_signature": manifest.ed25519_signature.hex(),
    }

    json_bytes = json.dumps(manifest_dict).encode("utf-8")

    # Build frame
    frame = BytesIO()
    frame.write(struct.pack("B", MANIFEST_VERSION))
    frame.write(struct.pack(">I", len(json_bytes)))
    frame.write(json_bytes)

    # CRC32C
    import crcmod
    crc_func = crcmod.mkCrcFun(0x11EDC6F41, initCrc=0, xorOut=0xffffffff)
    frame_data = frame.getvalue()
    crc = crc_func(frame_data)
    frame.write(struct.pack(">I", crc))

    return frame.getvalue()


def deserialize_manifest(data: bytes) -> TransferManifest:
    """
    Deserialize a TransferManifest from bytes.

    Parameters:
        data: Serialized manifest bytes.

    Returns:
        TransferManifest.

    Raises:
        ValueError: if format invalid or CRC fails.
    """
    # Verify minimum length
    if len(data) < 10:  # 1 + 4 + at least 1 + 4
        raise ValueError(f"Manifest too short: {len(data)} bytes")

    # Parse frame
    f = BytesIO(data)
    version = struct.unpack("B", f.read(1))[0]
    if version != MANIFEST_VERSION:
        raise ValueError(f"Unknown manifest version: {version}")

    length = struct.unpack(">I", f.read(4))[0]
    json_bytes = f.read(length)

    # Verify CRC
    import crcmod
    crc_func = crcmod.mkCrcFun(0x11EDC6F41, initCrc=0, xorOut=0xffffffff)
    frame_data = data[:-4]
    crc_expected = struct.unpack(">I", data[-4:])[0]
    crc_actual = crc_func(frame_data)

    if crc_actual != crc_expected:
        raise ValueError(
            f"CRC32C mismatch: expected {crc_expected:08x}, got {crc_actual:08x}"
        )

    # Parse JSON
    manifest_dict = json.loads(json_bytes.decode("utf-8"))

    return TransferManifest(
        transfer_id=manifest_dict["transfer_id"],
        sender_node_id=manifest_dict["sender_node_id"],
        protocol_version=manifest_dict["protocol_version"],
        file_name=manifest_dict["file_name"],
        file_size=manifest_dict["file_size"],
        file_sha256=manifest_dict["file_sha256"],
        chunk_size=manifest_dict["chunk_size"],
        total_chunks=manifest_dict["total_chunks"],
        rs_n=manifest_dict["rs_n"],
        rs_k=manifest_dict["rs_k"],
        num_passes=manifest_dict["num_passes"],
        overhead_ratio=manifest_dict["overhead_ratio"],
        interleave_depth=manifest_dict["interleave_depth"],
        window_size_bytes=manifest_dict["window_size_bytes"],
        total_windows=manifest_dict["total_windows"],
        merkle_root=manifest_dict["merkle_root"],
        mime_type=manifest_dict["mime_type"],
        creation_timestamp=manifest_dict["creation_timestamp"],
        classification_level=manifest_dict["classification_level"],
        expiration_policy=manifest_dict["expiration_policy"],
        ed25519_signature=bytes.fromhex(manifest_dict["ed25519_signature"]),
    )


def serialize_window_manifest(window: WindowManifest) -> bytes:
    """Serialize a WindowManifest to bytes."""
    window_dict = {
        "transfer_id": window.transfer_id,
        "window_id": window.window_id,
        "window_offset": window.window_offset,
        "window_size": window.window_size,
        "chunk_count": window.chunk_count,
        "chunk_count_with_rs": window.chunk_count_with_rs,
        "padding_length": window.padding_length,
        "window_merkle_root": window.window_merkle_root,
    }

    json_bytes = json.dumps(window_dict).encode("utf-8")
    frame = BytesIO()
    frame.write(struct.pack("B", MANIFEST_VERSION))
    frame.write(struct.pack(">I", len(json_bytes)))
    frame.write(json_bytes)

    # CRC32C
    import crcmod
    crc_func = crcmod.mkCrcFun(0x11EDC6F41, initCrc=0, xorOut=0xffffffff)
    frame_data = frame.getvalue()
    crc = crc_func(frame_data)
    frame.write(struct.pack(">I", crc))

    return frame.getvalue()


def deserialize_window_manifest(data: bytes) -> WindowManifest:
    """Deserialize a WindowManifest from bytes."""
    if len(data) < 10:
        raise ValueError(f"Window manifest too short: {len(data)} bytes")

    f = BytesIO(data)
    version = struct.unpack("B", f.read(1))[0]
    if version != MANIFEST_VERSION:
        raise ValueError(f"Unknown manifest version: {version}")

    length = struct.unpack(">I", f.read(4))[0]
    json_bytes = f.read(length)

    # Verify CRC
    import crcmod
    crc_func = crcmod.mkCrcFun(0x11EDC6F41, initCrc=0, xorOut=0xffffffff)
    frame_data = data[:-4]
    crc_expected = struct.unpack(">I", data[-4:])[0]
    crc_actual = crc_func(frame_data)

    if crc_actual != crc_expected:
        raise ValueError(
            f"CRC32C mismatch: expected {crc_expected:08x}, got {crc_actual:08x}"
        )

    window_dict = json.loads(json_bytes.decode("utf-8"))

    return WindowManifest(
        transfer_id=window_dict["transfer_id"],
        window_id=window_dict["window_id"],
        window_offset=window_dict["window_offset"],
        window_size=window_dict["window_size"],
        chunk_count=window_dict["chunk_count"],
        chunk_count_with_rs=window_dict["chunk_count_with_rs"],
        padding_length=window_dict["padding_length"],
        window_merkle_root=window_dict["window_merkle_root"],
    )
