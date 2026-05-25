"""
Multi-pass fountain encoding wrapper.
Calls IFountainEncoder — never imports LTEncoder directly.
Assigns correct pass_id to each packet.
Seeds come from m8_multipass — always different per pass.
"""
from __future__ import annotations
import logging
from common.models import EncodedPacket
from fountain.interface import get_encoder
from sender.m8_multipass import seed_for_pass

logger = logging.getLogger(__name__)


def encode_window(
    transfer_id    : str,
    window_id      : int,
    chunks         : list[bytes],
    num_passes     : int,
    overhead_ratio : float,
    codec          : str = "lt",
) -> list[EncodedPacket]:
    """
    Encode chunks with num_passes independent passes.
    Each pass uses a different seed → different XOR combinations.
    All packets from all passes are returned in one flat list.
    The pooler on the receiver side combines them into one decode pool.
    """
    if not chunks:
        raise ValueError("chunks cannot be empty")
    if not 1 <= num_passes <= 2:
        raise ValueError(f"num_passes must be 1 or 2, got {num_passes}")

    encoder    = get_encoder(codec)
    all_pkts   = []

    for pid in range(num_passes):
        seed    = seed_for_pass(transfer_id, window_id, pid)
        packets = encoder.encode(chunks, seed=seed, overhead_ratio=overhead_ratio)
        for p in packets:
            p.pass_id = pid
        all_pkts.extend(packets)
        logger.debug(f"Pass {pid}: {len(packets)} packets (seed={seed})")

    logger.debug(f"Total encoded: {len(all_pkts)} packets across {num_passes} passes")
    return all_pkts
