"""
sender/m4_rs_encoder.py — High-Performance Reed-Solomon Encoder
"""

from __future__ import annotations
import reedsolo
import logging
import re
import numpy as np
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
    Optimized version using NumPy for fast interleaving.
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")
    
    if rs_config.num_parity == 0:
        return list(chunks)

    chunk_size = len(chunks[0])
    codec = reedsolo.RSCodec(rs_config.num_parity)
    
    final_chunks = []
    # Process in blocks of size 'k'
    for i in range(0, len(chunks), rs_config.k):
        block = chunks[i:i+rs_config.k]
        
        # Pad last block if needed
        if len(block) < rs_config.k:
            block = list(block) + [b"\x00" * chunk_size] * (rs_config.k - len(block))
            
        final_chunks.extend(block)
        
        # Fast Interleaving with NumPy
        # Convert list of bytes to k x chunk_size array
        block_data = np.frombuffer(b"".join(block), dtype=np.uint8).reshape(rs_config.k, chunk_size)
        
        # Pre-allocate parity array (num_parity x chunk_size)
        parity_data = np.zeros((rs_config.num_parity, chunk_size), dtype=np.uint8)
        
        # Transpose so we can iterate over byte-columns easily
        # columns is chunk_size x k
        columns = block_data.T
        
        for col_idx in range(chunk_size):
            # Encode one byte-stripe
            # reedsolo encode() returns data + parity
            # We only need parity
            stripe = columns[col_idx]
            full_encoded = codec.encode(stripe)
            parity_data[:, col_idx] = list(full_encoded[rs_config.k:])
                
        for pc in parity_data:
            final_chunks.append(pc.tobytes())
            
    return final_chunks


def decode_with_rs(
    chunks_with_erasures : list[bytes | None],
    rs_config            : RSConfig,
) -> list[bytes]:
    """
    Reed-Solomon decoding.
    Optimized with NumPy.
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
            
        # Recovery with NumPy
        # Create a buffer for the whole block (n x chunk_size)
        block_buf = np.zeros((rs_config.n, chunk_size), dtype=np.uint8)
        for j, c in enumerate(block):
            if c is not None:
                block_buf[j] = np.frombuffer(c, dtype=np.uint8)
        
        # Transpose to chunk_size x n
        columns = block_buf.T
        recovered_block = np.zeros((rs_config.k, chunk_size), dtype=np.uint8)
        
        for col_idx in range(chunk_size):
            stripe = columns[col_idx]
            try:
                # decode() returns (decoded_msg, decoded_full, erasures_count)
                decoded, _, _ = codec.decode(stripe, erase_pos=erasures_pos)
                recovered_block[:, col_idx] = list(decoded)
            except Exception as e:
                # If decode fails, we might have to fill with zeros or re-raise
                logger.error(f"RS decode failed at col {col_idx}: {e}")
                # For robustness, we could just keep the zero initialization for this stripe
                
        for rb in recovered_block:
            recovered_data.append(rb.tobytes())
            
    return recovered_data
