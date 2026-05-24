"""
sender/m4_rs_encoder.py — Reed-Solomon Encoder

Role:
Adds Reed-Solomon parity chunks to each window's chunk list before fountain
encoding. Creates a second recovery layer at the chunk level.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List
import reedsolo


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
        if self.num_parity < 1:
            raise ValueError(f"RS parity count must be >= 1, got {self.num_parity}")


def parse_rs_config(config_str: str) -> RSConfig:
    """
    Parse RS config string like "RS(16,2)" into RSConfig.
    """
    config_str = config_str.strip()
    if not config_str.startswith("RS(") or not config_str.endswith(")"):
        raise ValueError(f"Invalid RS config format: {config_str!r}, expected 'RS(n,k)'")
    
    inner = config_str[3:-1]  # Extract "n,k"
    parts = inner.split(",")
    if len(parts) != 2:
        raise ValueError(f"Invalid RS config format: {config_str!r}, expected 'RS(n,k)'")
    
    try:
        n, k = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        raise ValueError(f"Invalid RS config format: {config_str!r}, n and k must be integers")
    
    return RSConfig(n=n, k=k)


import numpy as np

def encode_with_rs(chunks: List[bytes], rs_config: RSConfig) -> List[bytes]:
    """
    Encode chunks with Reed-Solomon parity using NumPy for speed.
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")
    
    chunk_size = len(chunks[0])
    K_total = len(chunks)
    num_blocks = (K_total + rs_config.k - 1) // rs_config.k
    
    rs = reedsolo.RSCodec(rs_config.num_parity)
    all_chunks_with_parity = []
    
    for b in range(num_blocks):
        block_start = b * rs_config.k
        block_end = min((b + 1) * rs_config.k, K_total)
        block_chunks_data = chunks[block_start:block_end]
        
        # Pad last block if needed
        if len(block_chunks_data) < rs_config.k:
            padding = [b"\x00" * chunk_size for _ in range(rs_config.k - len(block_chunks_data))]
            block_chunks_data.extend(padding)
        
        # Prepare matrix (k x chunk_size)
        block_matrix = np.stack([np.frombuffer(c, dtype=np.uint8) for c in block_chunks_data])
        
        # Parity matrix (num_parity x chunk_size)
        parity_matrix = np.zeros((rs_config.num_parity, chunk_size), dtype=np.uint8)
        
        # Apply RS across chunks
        for j in range(chunk_size):
            byte_slice = block_matrix[:, j].tobytes()
            encoded = rs.encode(byte_slice)
            # Extracted parity bytes
            parity_matrix[:, j] = np.frombuffer(encoded[rs_config.k:], dtype=np.uint8)
        
        # Add to result
        all_chunks_with_parity.extend(block_chunks_data)
        for p in range(rs_config.num_parity):
            all_chunks_with_parity.append(parity_matrix[p, :].tobytes())
            
    return all_chunks_with_parity


def decode_with_rs(chunks_with_erasures: List[bytes | None], rs_config: RSConfig) -> List[bytes]:
    """
    Decode chunks with Reed-Solomon using NumPy for speed.
    """
    if not chunks_with_erasures:
        raise ValueError("chunks list cannot be empty")
    
    chunk_size = next(len(c) for c in chunks_with_erasures if c is not None)
    num_blocks = len(chunks_with_erasures) // rs_config.n
    rs = reedsolo.RSCodec(rs_config.num_parity)
    
    recovered_data_chunks = []
    
    for b in range(num_blocks):
        block_start = b * rs_config.n
        block_chunks = chunks_with_erasures[block_start : block_start + rs_config.n]
        
        erasures_pos = [i for i, c in enumerate(block_chunks) if c is None]
        
        if len(erasures_pos) > rs_config.num_parity:
            raise ValueError(f"Block {b}: Too many erasures ({len(erasures_pos)})")
            
        if not erasures_pos:
            recovered_data_chunks.extend(block_chunks[:rs_config.k])
            continue
            
        # Reconstruct block
        block_matrix = np.zeros((rs_config.n, chunk_size), dtype=np.uint8)
        for i, c in enumerate(block_chunks):
            if c is not None:
                block_matrix[i] = np.frombuffer(c, dtype=np.uint8)
        
        recovered_matrix = np.zeros((rs_config.k, chunk_size), dtype=np.uint8)
        
        for j in range(chunk_size):
            byte_slice = block_matrix[:, j].tobytes()
            try:
                decoded_msg, _, _ = reedsolo.rs_correct_msg(byte_slice, rs_config.num_parity, erase_pos=erasures_pos)
                recovered_matrix[:, j] = np.frombuffer(decoded_msg[:rs_config.k], dtype=np.uint8)
            except Exception as e:
                raise ValueError(f"RS failed at block {b}, byte {j}: {e}")
        
        for i in range(rs_config.k):
            recovered_data_chunks.append(recovered_matrix[i, :].tobytes())
            
    return recovered_data_chunks

