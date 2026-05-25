"""
sender/m4_rs_encoder.py — Real Reed-Solomon Encoder
"""

from __future__ import annotations
import reedsolo
import logging
import numpy as np
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
    Real Reed-Solomon encoding using reedsolo.RSCodec.
    Interleaved across chunks for chunk-level erasure recovery.
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")

    chunk_size = len(chunks[0])
    if any(len(c) != chunk_size for c in chunks):
        raise ValueError("All chunks must have same size")

    K_total = len(chunks)
    num_blocks = (K_total + rs_config.k - 1) // rs_config.k
    
    codec = reedsolo.RSCodec(rs_config.num_parity)
    all_chunks_with_parity = []
    
    for b in range(num_blocks):
        block_start = b * rs_config.k
        block_end = min((b + 1) * rs_config.k, K_total)
        block_data_chunks = chunks[block_start:block_end]
        
        # Pad last block if needed
        if len(block_data_chunks) < rs_config.k:
            padding = [b"\x00" * chunk_size for _ in range(rs_config.k - len(block_data_chunks))]
            block_data_chunks.extend(padding)
        
        # Interleave RS across chunks in this block
        data_matrix = np.stack([np.frombuffer(c, dtype=np.uint8) for c in block_data_chunks])
        parity_matrix = np.zeros((rs_config.num_parity, chunk_size), dtype=np.uint8)
        
        for j in range(chunk_size):
            message = data_matrix[:, j].tobytes()
            encoded = codec.encode(message)
            parity_bytes = encoded[rs_config.k:]
            parity_matrix[:, j] = np.frombuffer(parity_bytes, dtype=np.uint8)
            
        all_chunks_with_parity.extend(block_data_chunks)
        for p in range(rs_config.num_parity):
            all_chunks_with_parity.append(parity_matrix[p, :].tobytes())
            
    return all_chunks_with_parity


def decode_with_rs(
    chunks_with_erasures : list[bytes | None],
    rs_config            : RSConfig,
) -> list[bytes]:
    """
    Real RS recovery using reedsolo.
    Input:  K data chunks + parity chunks, some may be None
    Output: K data chunks with gaps filled, parity stripped
    """
    if not chunks_with_erasures:
        raise ValueError("chunks list cannot be empty")

    # Get chunk_size from first non-None chunk
    chunk_size = None
    for c in chunks_with_erasures:
        if c is not None:
            chunk_size = len(c)
            break
    if chunk_size is None:
        raise ValueError("All chunks are None, cannot decode")

    num_blocks = len(chunks_with_erasures) // rs_config.n
    codec = reedsolo.RSCodec(rs_config.num_parity)
    
    recovered_data_chunks = []
    
    for b in range(num_blocks):
        block_start = b * rs_config.n
        block_chunks = chunks_with_erasures[block_start : block_start + rs_config.n]
        
        erasures_pos = [i for i, c in enumerate(block_chunks) if c is None]
        
        if len(erasures_pos) > rs_config.num_parity:
            raise ValueError(f"Too many erasures ({len(erasures_pos)}) for parity ({rs_config.num_parity})")
            
        if not erasures_pos:
            recovered_data_chunks.extend(block_chunks[:rs_config.k])
            continue
            
        # Reconstruct block matrix
        block_matrix = np.zeros((rs_config.n, chunk_size), dtype=np.uint8)
        for i, c in enumerate(block_chunks):
            if c is not None:
                block_matrix[i] = np.frombuffer(c, dtype=np.uint8)
        
        recovered_matrix = np.zeros((rs_config.k, chunk_size), dtype=np.uint8)
        
        for j in range(chunk_size):
            byte_slice = block_matrix[:, j].tobytes()
            try:
                decoded, _, _ = codec.decode(byte_slice, erase_pos=erasures_pos)
                recovered_matrix[:, j] = np.frombuffer(decoded[:rs_config.k], dtype=np.uint8)
            except reedsolo.ReedSolomonError as e:
                raise ValueError(f"RS decode failed: {e}") from e
        
        for i in range(rs_config.k):
            recovered_data_chunks.append(recovered_matrix[i, :].tobytes())
            
    return recovered_data_chunks
