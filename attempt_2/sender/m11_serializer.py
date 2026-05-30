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
    """
    Binary packet serialization.
    Format:
    - transfer_id: 8 bytes (truncated)
    - window_id: I (4)
    - pass_id: B (1)
    - packet_id: I (4)
    - seed: Q (8)
    - degree: H (2)
    - K_prime: I (4)
    - padding_length: I (4)
    - data_chunk_count: I (4)
    - crc32c: I (4)
    - blake3_mac: 32 bytes
    - chunk_ids: H * degree (2 * degree)
    - data: remaining bytes
    """
    tid_bin = pkt_dict["transfer_id"][:8].encode()
    if len(tid_bin) < 8: tid_bin = tid_bin.ljust(8, b"\0")

    degree = pkt_dict["degree"]
    chunk_ids_fmt = f"{degree}H"

    header = struct.pack(
        ">8sIBIQHIIII32s",
        tid_bin,
        pkt_dict["window_id"],
        pkt_dict["pass_id"],
        pkt_dict["packet_id"],
        pkt_dict["seed"],
        degree,
        pkt_dict["K_prime"],
        pkt_dict["padding_length"],
        pkt_dict["data_chunk_count"],
        pkt_dict["crc32c"],
        pkt_dict["blake3_mac"]
    )

    chunk_ids_bin = struct.pack(">" + chunk_ids_fmt, *pkt_dict["chunk_ids"])
    payload = header + chunk_ids_bin + pkt_dict["data"]

    return _frame(PACKET_VERSION, payload)


def deserialize_packet(data: bytes) -> dict | None:
    payload = _unframe(data, PACKET_VERSION)
    if payload is None:
        return None

    if len(payload) < 75: # Min header size without chunk_ids
        return None

    try:
        header_len = 75
        header = struct.unpack(">8sIBIQHIIII32s", payload[:header_len])

        tid_bin          = header[0].decode(errors="replace").strip("\0")
        window_id        = header[1]
        pass_id          = header[2]
        packet_id        = header[3]
        seed             = header[4]
        degree           = header[5]
        K_prime          = header[6]
        padding_length   = header[7]
        data_chunk_count = header[8]
        crc32c           = header[9]
        blake3_mac       = header[10]

        chunk_ids_start = header_len
        chunk_ids_end = chunk_ids_start + (2 * degree)

        chunk_ids_fmt = f">{degree}H"
        chunk_ids = list(struct.unpack(chunk_ids_fmt, payload[chunk_ids_start:chunk_ids_end]))

        pkt_data = payload[chunk_ids_end:]

        return {
            "transfer_id"      : tid_bin, # Note: this is only first 8 chars
            "window_id"        : window_id,
            "pass_id"          : pass_id,
            "packet_id"        : packet_id,
            "seed"             : seed,
            "degree"           : degree,
            "chunk_ids"        : chunk_ids,
            "K_prime"          : K_prime,
            "padding_length"   : padding_length,
            "data_chunk_count" : data_chunk_count,
            "data"             : pkt_data, # bytes
            "crc32c"           : crc32c,
            "blake3_mac"       : blake3_mac, # bytes
        }
    except Exception as e:
        logger.debug(f"Packet deserialize error: {e}")
        return None
