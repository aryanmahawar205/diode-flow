"""
sender/m6_fountain_encoder.py — Fountain Encoder Wrapper

Role:
Wraps IFountainEncoder to handle multi-pass encoding and pass_id assignment.
The pipeline calls this module — it does not call lt_encoder.py directly.
This keeps the pipeline clean and codec-agnostic.

Design:
- Codec selection via registry: encoder = get_encoder("lt")
- Multi-pass: calls encoder.encode() separately for each pass with different seeds
- Sets pass_id on each packet accordingly
- Seeds are derived deterministically from transfer_id + window_id + pass_id

Codec swapping:
To switch from LT to RaptorQ when ready:
  encoder = get_encoder("raptorq")
No other code changes needed — abstraction handles it.
"""

from typing import List
from data_diode.fountain.interface import get_encoder, EncodedPacket
from data_diode.sender.m7_multipass import seed_for_pass


def encode_window_multipass(
    transfer_id: str,
    window_id: int,
    chunks: List[bytes],
    num_passes: int,
    overhead_ratio: float,
) -> List[EncodedPacket]:
    """
    Encode chunks with multi-pass fountain encoding.
    
    Args:
        transfer_id: Transfer UUID
        window_id: Window index
        chunks: List of chunks (same size, from m4_rs_encoder output)
        num_passes: Number of passes (1-3)
        overhead_ratio: Overhead per pass (0.15-0.25)
    
    Returns:
        All encoded packets from all passes
    """
    if num_passes < 1 or num_passes > 3:
        raise ValueError(f"num_passes must be 1-3, got {num_passes}")
    
    if overhead_ratio <= 0 or overhead_ratio > 0.5:
        raise ValueError(f"overhead_ratio must be 0-0.5, got {overhead_ratio}")
    
    if not chunks:
        raise ValueError("chunks list cannot be empty")
    
    # Get encoder (LT or RaptorQ depending on registry)
    encoder = get_encoder("lt")
    
    K = len(chunks)
    all_packets = []
    
    # Encode each pass independently with different seed
    for pass_id in range(num_passes):
        # Generate deterministic seed for this pass
        seed = seed_for_pass(transfer_id, window_id, pass_id)
        
        # Encode chunks with this seed
        encoded_result = encoder.encode(chunks, seed=seed, overhead_ratio=overhead_ratio)
        
        # Assign pass_id to each packet
        for packet in encoded_result.packets:
            packet.pass_id = pass_id
        
        all_packets.extend(encoded_result.packets)
    
    return all_packets


def get_expected_packet_count(K: int, num_passes: int, overhead_ratio: float) -> int:
    """
    Calculate expected total packet count for multi-pass encoding.
    
    Args:
        K: Number of chunks
        num_passes: Number of passes
        overhead_ratio: Overhead ratio per pass
    
    Returns:
        Expected total packets across all passes
    """
    packets_per_pass = int(K * (1 + overhead_ratio))
    return packets_per_pass * num_passes
