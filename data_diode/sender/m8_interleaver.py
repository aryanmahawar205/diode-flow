"""
sender/m8_interleaver.py — Packet Interleaver
"""

from __future__ import annotations
from typing import List
from fountain.interface import EncodedPacket


def interleave_encoded_packets(
    packets_by_pass: List[List[EncodedPacket]],
    stride: int
) -> List[EncodedPacket]:
    """
    Interleave packets across passes and within each pass.
    """
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")
    
    if not packets_by_pass:
        return []

    # Interleave each pass independently using stride
    interleaved_passes = []
    for pkts in packets_by_pass:
        if not pkts:
            continue   # skip empty passes gracefully
            
        reordered = []
        for offset in range(stride):
            for i in range(offset, len(pkts), stride):
                reordered.append(pkts[i])
        interleaved_passes.append(reordered)
    
    if not interleaved_passes:
        return []

    # Interleave reordered passes together (round-robin)
    result = []
    max_packets = max(len(p) for p in interleaved_passes)
    
    for position in range(max_packets):
        for p_list in interleaved_passes:
            if position < len(p_list):
                result.append(p_list[position])
    
    return result


def interleave_packets(packets_by_pass: List[List[int]], stride: int) -> List[tuple[int, int]]:
    """
    Legacy interleave_packets for integer IDs.
    Returns (pass_id, logical_packet_id) tuples.
    """
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")
    
    if not packets_by_pass:
        return []
    
    # Skip empty passes instead of raising
    interleaved_passes = []
    for pass_id, packets in enumerate(packets_by_pass):
        if not packets:
            continue
        # Stride interleave
        reordered = []
        for offset in range(stride):
            for i in range(offset, len(packets), stride):
                reordered.append(packets[i])
        interleaved_passes.append([(pass_id, pkt) for pkt in reordered])
    
    if not interleaved_passes:
        return []

    result = []
    max_packets = max(len(p) for p in interleaved_passes)
    for position in range(max_packets):
        for p_list in interleaved_passes:
            if position < len(p_list):
                result.append(p_list[position])
    
    return result
