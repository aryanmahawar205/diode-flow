"""
sender/m4_rs_encoder.py — High-Performance Reed-Solomon Encoder
"""

from __future__ import annotations
import reedsolo
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class RSConfig:
    """Reed-Solomon configuration."""
    n: int                  # Total symbols (data + parity)
    k: int                  # Data symbols
    
    @property
    def num_parity(self) -> int:
        """Number of parity symbols."""
        return self.n - self.k

    def __post_init__(self):
        """Validate RS parameters."""
        if not (1 <= self.k <= self.n <= 255):
            raise ValueError(f"Invalid RS config RS({self.n}, {self.k}): must have 1 <= k <= n <= 255")
        if self.num_parity < 0:
            raise ValueError(f"RS parity count must be >= 0, got {self.num_parity}")

def parse_rs_config(config_str: str) -> RSConfig:
    """Parse RS config string like 'RS(16,2)'."""
    m = re.search(r"RS\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", config_str.strip())
    if not m:
        raise ValueError(f"Invalid RS config format: {config_str!r}, expected 'RS(n,k)'")
    return RSConfig(n=int(m.group(1)), k=int(m.group(2)))


def encode_with_rs(chunks: list[bytes], rs_config: RSConfig) -> list[bytes]:
    """
    Reed-Solomon encoding using reedsolo.
    Ultra-fast version: encodes across chunks in blocks.
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")
    
    if rs_config.num_parity == 0:
        return list(chunks)

    chunk_size = len(chunks[0])
    codec = reedsolo.RSCodec(rs_config.num_parity)
    
    # Process in blocks of size 'k'
    final_chunks = []
    for i in range(0, len(chunks), rs_config.k):
        block = chunks[i:i+rs_config.k]
        
        # Pad last block if needed
        if len(block) < rs_config.k:
            block = list(block) + [b"\x00" * chunk_size] * (rs_config.k - len(block))
            
        final_chunks.extend(block)
        
        # INTERLEAVE: encode one parity chunk per data chunk in block (byte-wise)
        # This is expensive in Python. To be FAST, we use a simpler approach:
        # We just generate parity chunks for the whole block of chunks.
        
        parity_chunks = [bytearray(chunk_size) for _ in range(rs_config.num_parity)]
        
        # Optimization: encode byte-slices of chunks
        for byte_idx in range(chunk_size):
            msg = bytes([c[byte_idx] for c in block])
            # encode() returns data + parity
            full_encoded = codec.encode(msg)
            parity_only = full_encoded[rs_config.k:]
            for p_idx, p_val in enumerate(parity_only):
                parity_chunks[p_idx][byte_idx] = p_val
                
        for pc in parity_chunks:
            final_chunks.append(bytes(pc))
            
    return final_chunks


def decode_with_rs(
    chunks_with_erasures : list[bytes | None],
    rs_config            : RSConfig,
) -> list[bytes]:
    """
    Reed-Solomon decoding.
    """
    if not chunks_with_erasures:
        return []
    
    if rs_config.num_parity == 0:
        return [c if c is not None else b"" for c in chunks_with_erasures]

    chunk_size = next(len(c) for c in chunks_with_erasures if c is not None)
    codec = reedsolo.RSCodec(rs_config.num_parity)
    
    # Split into blocks of size 'n'
    recovered_data = []
    for i in range(0, len(chunks_with_erasures), rs_config.n):
        block = chunks_with_erasures[i:i+rs_config.n]
        if len(block) < rs_config.n:
            # Trailing chunks without parity?
            recovered_data.extend([c if c is not None else b"\x00"*chunk_size for c in block])
            continue
            
        erasures_pos = [j for j, c in enumerate(block) if c is None]
        if not erasures_pos:
            recovered_data.extend([bytes(c) for c in block[:rs_config.k]])
            continue
            
        if len(erasures_pos) > rs_config.num_parity:
            raise ValueError(f"Too many erasures ({len(erasures_pos)}) for parity ({rs_config.num_parity})")
            
        # Recovery
        recovered_block = [bytearray(chunk_size) for _ in range(rs_config.k)]
        for byte_idx in range(chunk_size):
            msg = bytearray(rs_config.n)
            for j, c in enumerate(block):
                if c is not None:
                    msg[j] = c[byte_idx]
                else:
                    msg[j] = 0
            
            # Decode using erasures
            try:
                decoded, _, _ = codec.decode(msg, erase_pos=erasures_pos)
                for k_idx in range(rs_config.k):
                    recovered_block[k_idx][byte_idx] = decoded[k_idx]
            except Exception as e:
                raise ValueError(f"RS decode failed: {e}")
                
        for rb in recovered_block:
            recovered_data.append(bytes(rb))
            
    return recovered_data
