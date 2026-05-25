"""
Reorders packet transmission to spread burst loss.
Stride interleaving: packets[0], packets[stride], packets[2*stride], ...
Cross-pass interleaving: round-robin between passes.
A 500-packet burst at stride=4 hits 4 different logical regions, not one.
"""
from __future__ import annotations
from common.models import EncodedPacket


def interleave(packets: list[EncodedPacket], stride: int) -> list[EncodedPacket]:
    """
    Stride-based interleaving of a single pass.
    stride=4: [0,4,8,..., 1,5,9,..., 2,6,10,..., 3,7,11,...]
    """
    if stride <= 1:
        return packets
    result = []
    for offset in range(stride):
        result.extend(packets[offset::stride])
    return result


def interleave_multipass(packets_by_pass: list[list[EncodedPacket]],
                          stride: int) -> list[EncodedPacket]:
    """
    Interleave within each pass, then round-robin across passes.
    TX order: [p0_pass0, p0_pass1, p1_pass0, p1_pass1, ...]
    A burst can't wipe an entire pass.
    """
    passes_interleaved = [interleave(p, stride) for p in packets_by_pass if p]

    result  = []
    max_len = max((len(p) for p in passes_interleaved), default=0)
    for i in range(max_len):
        for p in passes_interleaved:
            if i < len(p):
                result.append(p[i])
    return result
