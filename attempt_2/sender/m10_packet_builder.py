"""
Attaches security envelope to each packet.
CRC32C: fast corruption detection (hardware-accelerated).
BLAKE3-MAC: cryptographic tamper detection.
Covers metadata + payload — not payload alone.
"""
from __future__ import annotations
import hmac as hmac_lib
import logging
import struct
import crcmod
import blake3
from common.models import EncodedPacket

logger = logging.getLogger(__name__)

# Module-level CRC — computed once, reused for every packet
_CRC32C = crcmod.mkCrcFun(0x11EDC6F41, rev=True, initCrc=0xffffffff, xorOut=0xffffffff)


def compute_crc32c(data: bytes) -> int:
    return _CRC32C(data) & 0xFFFFFFFF


def compute_blake3_mac(data: bytes, key: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("BLAKE3 key must be exactly 32 bytes")
    return blake3.blake3(data, key=key).digest()


def verify_blake3_mac(data: bytes, key: bytes, expected: bytes) -> bool:
    actual = compute_blake3_mac(data, key)
    return hmac_lib.compare_digest(actual, expected)   # timing-safe


def attach_security(packet: EncodedPacket, transfer_id: str,
                    window_id: int, padding_length: int, 
                    data_chunk_count: int, shared_key: bytes) -> dict:
    """
    Build full packet dict with security fields.
    MAC covers all metadata + payload.
    """
    meta_bytes = (f"{transfer_id}:{window_id}:{packet.pass_id}:"
                  f"{packet.packet_id}:{packet.degree}:{packet.seed}:"
                  f"{padding_length}:{data_chunk_count}").encode()
    mac_input  = meta_bytes + packet.data

    crc  = compute_crc32c(mac_input)
    mac  = compute_blake3_mac(mac_input, shared_key)

    return {
        "transfer_id"      : transfer_id,
        "window_id"        : window_id,
        "pass_id"          : packet.pass_id,
        "packet_id"        : packet.packet_id,
        "seed"             : packet.seed,
        "degree"           : packet.degree,
        "chunk_ids"        : packet.chunk_ids,
        "K_prime"          : packet.source_chunk_count,
        "padding_length"   : padding_length,
        "data_chunk_count" : data_chunk_count,
        "data"             : packet.data.hex(),
        "crc32c"           : crc,
        "blake3_mac"       : mac.hex(),
    }
