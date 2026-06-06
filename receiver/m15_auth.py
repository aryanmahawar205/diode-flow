"""
receiver/m15_auth.py — Authentication verifier for receiver pipeline.

Role:
Verify per-packet BLAKE3-MACs.
"""

from __future__ import annotations

import hmac
import logging
import blake3

logger = logging.getLogger(__name__)

def compute_blake3_mac(data: bytes, shared_secret: bytes) -> bytes:
    if len(shared_secret) != 32:
        raise ValueError("BLAKE3 key must be exactly 32 bytes")
    return blake3.blake3(data, key=shared_secret).digest()

def verify_packet_mac(pkt_dict: dict, shared_secret: bytes) -> bool:
    """
    Reconstruct the MAC input from the packet dict and verify the MAC.
    """
    try:
        transfer_id      = pkt_dict["transfer_id"]
        window_id        = pkt_dict["window_id"]
        pass_id          = pkt_dict["pass_id"]
        packet_id        = pkt_dict["packet_id"]
        degree           = pkt_dict["degree"]
        seed             = pkt_dict["seed"]
        padding_length   = pkt_dict["padding_length"]
        data_chunk_count = pkt_dict["data_chunk_count"]
        data             = pkt_dict["data"]
        expected_mac     = pkt_dict["blake3_mac"]

        meta_bytes = (f"{transfer_id}:{window_id}:{pass_id}:"
                      f"{packet_id}:{degree}:{seed}:"
                      f"{padding_length}:{data_chunk_count}").encode()
        mac_input  = meta_bytes + data

        if packet_id == 0:
            logger.info(
                f"MAC CHECK: transfer_id={transfer_id} "
                f"mac_len={len(expected_mac)} "
                f"data_len={len(data)}"
            )
            
        actual_mac = compute_blake3_mac(mac_input, shared_secret)
        return hmac.compare_digest(actual_mac, expected_mac)
    except Exception as e:
        logger.warning(f"MAC verification failed with error: {e}")
        return False
