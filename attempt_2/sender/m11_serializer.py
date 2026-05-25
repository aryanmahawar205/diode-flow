"""
Serializes packets and manifests to bytes for UDP transmission.
Format: 1-byte version | 4-byte length (big-endian) | JSON payload | 4-byte CRC32C
Human-readable JSON for easy debugging. CRC32C for corruption detection.
"""
from __future__ import annotations
import json
import logging
import struct
from io import BytesIO
from common.models import TransferManifest, EncodedPacket
import crcmod

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1
PACKET_VERSION   = 2

# Module-level — computed once
_CRC32C = crcmod.mkCrcFun(0x11EDC6F41, rev=True, initCrc=0xffffffff, xorOut=0xffffffff)


def _frame(version: int, payload: bytes) -> bytes:
    buf = BytesIO()
    buf.write(struct.pack("B", version))
    buf.write(struct.pack(">I", len(payload)))
    buf.write(payload)
    crc = _CRC32C(buf.getvalue()) & 0xFFFFFFFF
    buf.write(struct.pack(">I", crc))
    return buf.getvalue()


def _unframe(data: bytes, expected_version: int) -> bytes | None:
    if len(data) < 10:
        return None
    version = struct.unpack("B", data[:1])[0]
    if version != expected_version:
        return None
    length  = struct.unpack(">I", data[1:5])[0]
    payload = data[5:5 + length]
    if len(payload) != length:
        return None
    crc_exp = struct.unpack(">I", data[-4:])[0]
    crc_act = _CRC32C(data[:-4]) & 0xFFFFFFFF
    if crc_act != crc_exp:
        logger.debug("CRC32C mismatch on deserialization")
        return None
    return payload


def serialize_manifest(m: TransferManifest) -> bytes:
    d = {
        "transfer_id"           : m.transfer_id,
        "sender_node_id"        : m.sender_node_id,
        "protocol_version"      : m.protocol_version,
        "file_name"             : m.file_name,
        "file_size"             : m.file_size,
        "file_sha256"           : m.file_sha256,
        "original_size"         : m.original_size,
        "original_sha256"       : m.original_sha256,
        "compression_algorithm" : m.compression_algorithm,
        "chunk_size"            : m.chunk_size,
        "total_chunks"          : m.total_chunks,
        "total_windows"         : m.total_windows,
        "window_size_bytes"     : m.window_size_bytes,
        "rs_n"                  : m.rs_n,
        "rs_k"                  : m.rs_k,
        "num_passes"            : m.num_passes,
        "overhead_ratio"        : m.overhead_ratio,
        "interleave_depth"      : m.interleave_depth,
        "merkle_root"           : m.merkle_root,
        "mime_type"             : m.mime_type,
        "creation_timestamp"    : m.creation_timestamp,
        "classification_level"  : m.classification_level,
        "expiration_policy"     : m.expiration_policy,
        "ed25519_signature"     : m.ed25519_signature.hex(),
    }
    return _frame(MANIFEST_VERSION, json.dumps(d).encode())


def deserialize_manifest(data: bytes) -> TransferManifest | None:
    payload = _unframe(data, MANIFEST_VERSION)
    if payload is None:
        return None
    try:
        d = json.loads(payload)
        return TransferManifest(
            transfer_id=d["transfer_id"], sender_node_id=d["sender_node_id"],
            protocol_version=d["protocol_version"], file_name=d["file_name"],
            file_size=d["file_size"], file_sha256=d["file_sha256"],
            original_size=d["original_size"], original_sha256=d["original_sha256"],
            compression_algorithm=d["compression_algorithm"],
            chunk_size=d["chunk_size"], total_chunks=d["total_chunks"],
            total_windows=d["total_windows"], window_size_bytes=d["window_size_bytes"],
            rs_n=d["rs_n"], rs_k=d["rs_k"], num_passes=d["num_passes"],
            overhead_ratio=d["overhead_ratio"], interleave_depth=d["interleave_depth"],
            merkle_root=d["merkle_root"], mime_type=d["mime_type"],
            creation_timestamp=d["creation_timestamp"],
            classification_level=d["classification_level"],
            expiration_policy=d["expiration_policy"],
            ed25519_signature=bytes.fromhex(d["ed25519_signature"]))
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        logger.debug(f"Manifest deserialize error: {e}")
        return None


def serialize_packet(pkt_dict: dict) -> bytes:
    """pkt_dict comes from m10_packet_builder.attach_security()"""
    return _frame(PACKET_VERSION, json.dumps(pkt_dict).encode())


def deserialize_packet(data: bytes) -> dict | None:
    payload = _unframe(data, PACKET_VERSION)
    if payload is None:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None
