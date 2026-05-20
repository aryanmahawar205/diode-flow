"""
sender/m8_interleaver.py — Packet Interleaver

Role:
Reorders the transmission sequence of encoded packets to spread burst loss
across the logical packet space.

Design:
Without interleaving, a 5-second network hiccup drops 500 consecutive packets
covering logical positions 300–800. That's a dense gap the decoder may not
bridge. With interleaving (stride S), those 500 physical-position packets are
spread across the entire logical space — no dense gap forms.

Interleave algorithm (stride-based):
  For stride S and N packets:
  - Transmit packet[0], packet[S], packet[2*S], ...
  - Then packet[1], packet[S+1], packet[2*S+1], ...
  - Continue for all offsets 0..S-1
  
Cross-pass interleaving: Packets from different passes are also interleaved
together so a burst doesn't wipe an entire pass:
  TX: [pass0_pkt0][pass1_pkt0][pass2_pkt0][pass0_pkt1][pass1_pkt1]...

Stride is determined by Transfer Profile (m5_profile.py).
"""

from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class InterleavedPacket:
    """Packet with transmission order."""
    tx_position: int          # Position in transmission sequence
    pass_id: int              # Which pass (0, 1, 2)
    logical_position: int     # Original packet_id within pass


def interleave_packets(packets_by_pass: List[List[int]], stride: int) -> List[Tuple[int, int]]:
    """
    Interleave packets from multiple passes.
    
    Args:
        packets_by_pass: List of pass-wise packet lists.
                        packets_by_pass[i] = [packet_id_0, packet_id_1, ...]
        stride: Interleave stride (typically 2-8 from Profile)
    
    Returns:
        List of (pass_id, logical_packet_id) tuples in transmission order
    
    Algorithm:
    1. Perform stride-based interleaving on each pass independently
    2. Interleave the passes together (round-robin by position)
    """
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")
    
    if not packets_by_pass:
        return []
    
    # Validate input
    num_passes = len(packets_by_pass)
    for pass_id, packets in enumerate(packets_by_pass):
        if not packets:
            raise ValueError(f"Pass {pass_id} has no packets")
    
    # Interleave each pass independently
    interleaved_passes = []
    for pass_id, packets in enumerate(packets_by_pass):
        interleaved = _stride_interleave(packets, stride)
        interleaved_passes.append([(pass_id, pkt) for pkt in interleaved])
    
    # Interleave passes together (round-robin by position)
    result = []
    max_packets = max(len(p) for p in interleaved_passes)
    
    for position in range(max_packets):
        for pass_id in range(num_passes):
            if position < len(interleaved_passes[pass_id]):
                result.append(interleaved_passes[pass_id][position])
    
    return result


def _stride_interleave(packets: List[int], stride: int) -> List[int]:
    """
    Perform stride-based interleaving on a single pass's packets.
    
    Args:
        packets: List of packet IDs
        stride: Stride (2-8)
    
    Returns:
        Reordered packet IDs
    """
    if not packets:
        return []
    
    interleaved = []
    
    # For each offset 0..stride-1
    for offset in range(stride):
        # Collect packets at this offset
        for i in range(offset, len(packets), stride):
            interleaved.append(packets[i])
    
    return interleaved


def create_transmission_order(num_packets_per_pass: List[int], stride: int) -> List[Tuple[int, int]]:
    """
    Create transmission order for multi-pass encoding.
    
    Args:
        num_packets_per_pass: List where index is pass_id, value is packet count
        stride: Interleave stride from Profile
    
    Returns:
        List of (pass_id, logical_packet_id) in order of transmission
    """
    # Generate logical packet lists
    packets_by_pass = [list(range(count)) for count in num_packets_per_pass]
    
    return interleave_packets(packets_by_pass, stride)
