"""
sender/m10_serializer.py — Optimized Binary Serialization
"""

from __future__ import annotations

import json
import logging
import struct
import crcmod
import base64
from io import BytesIO
from typing import Optional

from common.models import (
    TransferManifest,
    WindowManifest,
)
from fountain.interface import EncodedPacket

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 0x51
PACKET_VERSION   = 0x53 # Increment version for raw binary format

# crcmod at module level
_CRC32C = crcmod.mkCrcFun(0x11EDC6F41, rev=True, initCrc=0xffffffff, xorOut=0xffffffff)


def serialize_packet(packet: EncodedPacket) -> bytes:
    """
    Serialize EncodedPacket using fast binary framing.
    [Version 1B][MetaLen 4B][JSON Meta][Payload][CRC 4B]
    """
    meta_dict = {
        "p": packet.packet_id,
        "w": getattr(packet, 'window_id', 0),
        "s": packet.pass_id,
        "e": packet.seed,
        "d": packet.degree,
        "c": packet.chunk_ids,
        "k": packet.source_chunk_count,
    }
    meta_bytes = json.dumps(meta_dict, separators=(',', ':')).encode("utf-8")
    
    # Frame: Version(1) + MetaLen(4) + Meta + Payload
    header = struct.pack(">BI", PACKET_VERSION, len(meta_bytes))
    body = header + meta_bytes + packet.data
    
    crc = _CRC32C(body)
    return body + struct.pack(">I", crc)


def deserialize_packet(data: bytes) -> EncodedPacket | None:
    """
    Deserialize packet bytes. Fast raw binary version.
    """
    try:
        if len(data) < 10: return None
        
        version = data[0]
        if version != PACKET_VERSION:
            return _deserialize_packet_v52(data) # Fallback to hex-json version if needed
            
        meta_len = struct.unpack(">I", data[1:5])[0]
        if len(data) < 5 + meta_len + 4: return None
        
        meta_bytes = data[5:5+meta_len]
        payload = data[5+meta_len:-4]
        
        crc_exp = struct.unpack(">I", data[-4:])[0]
        crc_act = _CRC32C(data[:-4])
        if crc_act != crc_exp: return None
        
        d = json.loads(meta_bytes.decode("utf-8"))
        p = EncodedPacket(
            packet_id          = d["p"],
            window_id          = d["w"],
            pass_id            = d["s"],
            seed               = d["e"],
            degree             = d["d"],
            chunk_ids          = d["c"],
            data               = payload,
            source_chunk_count = d["k"],
        )
        return p
    except Exception:
        return None

def _deserialize_packet_v52(data: bytes) -> EncodedPacket | None:
    """Legacy hex-json deserializer."""
    try:
        if data[0] != 0x52: return None
        length = struct.unpack(">I", data[1:5])[0]
        json_bytes = data[5:5+length]
        d = json.loads(json_bytes.decode("utf-8"))
        p = EncodedPacket(
            packet_id          = d["packet_id"],
            window_id          = d.get("window_id", 0),
            pass_id            = d["pass_id"],
            seed               = d["seed"],
            degree             = d["degree"],
            chunk_ids          = d["chunk_ids"],
            data               = bytes.fromhex(d["data"]),
            source_chunk_count = d["source_chunk_count"],
        )
        return p
    except Exception:
        return None


def serialize_manifest(manifest: TransferManifest) -> bytes:
    """Serialize manifest to JSON with CRC."""
    manifest_dict = {
        "tid": manifest.transfer_id,
        "nid": manifest.sender_node_id,
        "ver": manifest.protocol_version,
        "name": manifest.file_name,
        "size": manifest.file_size,
        "hash": manifest.file_sha256,
        "cs": manifest.chunk_size,
        "tc": manifest.total_chunks,
        "rn": manifest.rs_n,
        "rk": manifest.rs_k,
        "np": manifest.num_passes,
        "or": manifest.overhead_ratio,
        "id": manifest.interleave_depth,
        "ws": manifest.window_size_bytes,
        "tw": manifest.total_windows,
        "mr": manifest.merkle_root,
        "mime": manifest.mime_type,
        "ts": manifest.creation_timestamp,
        "cl": manifest.classification_level,
        "ep": manifest.expiration_policy,
        "sig": manifest.ed25519_signature.hex(),
        "alg": manifest.compression_algorithm,
        "csz": manifest.compressed_size,
        "osz": manifest.original_size,
        "oh": manifest.original_sha256,
    }
    json_bytes = json.dumps(manifest_dict, separators=(',', ':')).encode("utf-8")
    body = struct.pack(">BI", MANIFEST_VERSION, len(json_bytes)) + json_bytes
    crc = _CRC32C(body)
    return body + struct.pack(">I", crc)


def deserialize_manifest(data: bytes) -> TransferManifest:
    """Deserialize manifest from JSON."""
    if len(data) < 10: raise ValueError("Manifest too short")
    version = data[0]
    if version != MANIFEST_VERSION: raise ValueError(f"Bad version: {version}")
    
    length = struct.unpack(">I", data[1:5])[0]
    json_bytes = data[5:5+length]
    
    crc_exp = struct.unpack(">I", data[-4:])[0]
    crc_act = _CRC32C(data[:-4])
    if crc_act != crc_exp: raise ValueError("CRC mismatch")
    
    d = json.loads(json_bytes.decode("utf-8"))
    return TransferManifest(
        transfer_id=d["tid"],
        sender_node_id=d["nid"],
        protocol_version=d["ver"],
        file_name=d["name"],
        file_size=d["size"],
        file_sha256=d["hash"],
        chunk_size=d["cs"],
        total_chunks=d["tc"],
        rs_n=d["rn"],
        rs_k=d["rk"],
        num_passes=d["np"],
        overhead_ratio=d["or"],
        interleave_depth=d["id"],
        window_size_bytes=d["ws"],
        total_windows=d["tw"],
        merkle_root=d["mr"],
        mime_type=d["mime"],
        creation_timestamp=d["ts"],
        classification_level=d["cl"],
        expiration_policy=d["ep"],
        ed25519_signature=bytes.fromhex(d["sig"]),
        compression_algorithm=d.get("alg", "none"),
        compressed_size=d.get("csz", 0),
        original_size=d.get("osz", 0),
        original_sha256=d.get("oh", ""),
    )
