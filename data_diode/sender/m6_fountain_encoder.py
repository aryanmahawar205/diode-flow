"""
sender/m6_fountain_encoder.py — Fountain Encoder Wrapper
"""

from __future__ import annotations
from typing import List
from fountain.interface import get_encoder, EncodedPacket
from sender.m7_multipass import seed_for_pass


def encode_window_multipass(
    transfer_id: str,
    window_id: int,
    chunks: List[bytes],
    num_passes: int,
    overhead_ratio: float,
    codec: str = "lt",
) -> List[EncodedPacket]:
    """
    Encode chunks with multi-pass fountain encoding.
    """
    if not (1 <= num_passes <= 2):
        raise ValueError(f"num_passes must be 1-2, got {num_passes}")
    
    if not chunks:
        raise ValueError("chunks list cannot be empty")
    
    # Get encoder (LT or RaptorQ depending on registry)
    encoder = get_encoder(codec)
    
    all_packets = []
    
    # Encode each pass independently with different seed
    for pass_id in range(num_passes):
        # Generate deterministic seed for this pass
        seed = seed_for_pass(transfer_id, window_id, pass_id)
        
        # Encode chunks with this seed
        encoded_packets = encoder.encode(chunks, seed=seed, overhead_ratio=overhead_ratio)
        
        # Assign metadata to each packet
        for p in encoded_packets:
            p.pass_id = pass_id
        
        all_packets.extend(encoded_packets)
    
    return all_packets


def get_expected_packet_count(K: int, num_passes: int, overhead_ratio: float) -> int:
    """Calculate expected total packet count."""
    import math
    packets_per_pass = math.ceil(K * (1 + overhead_ratio))
    return packets_per_pass * num_passes
