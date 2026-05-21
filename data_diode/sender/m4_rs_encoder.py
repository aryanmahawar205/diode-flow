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


def encode_with_rs(chunks: List[bytes], rs_config: RSConfig) -> List[bytes]:
    """
    Encode chunks with Reed-Solomon parity using reedsolo library.
    
    Handles multiple RS blocks if the number of chunks exceeds rs_config.k.
    
    Args:
        chunks: List of chunks (all must be same size)
        rs_config: RS(n, k) configuration
    
    Returns:
        Original chunks + parity chunks appended for each block
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")
    
    chunk_size = len(chunks[0])
    for i, chunk in enumerate(chunks):
        if len(chunk) != chunk_size:
            raise ValueError(f"Chunk {i} has size {len(chunk)}, expected {chunk_size}")
    
    # Split chunks into blocks of size rs_config.k
    K_total = len(chunks)
    num_blocks = (K_total + rs_config.k - 1) // rs_config.k
    
    rs = reedsolo.RSCodec(rs_config.num_parity)
    
    all_chunks_with_parity = []
    
    for b in range(num_blocks):
        block_start = b * rs_config.k
        block_end = min((b + 1) * rs_config.k, K_total)
        block_chunks = chunks[block_start:block_end]
        
        # Pad last block if needed to rs_config.k
        if len(block_chunks) < rs_config.k:
            padding = [b"\x00" * chunk_size for _ in range(rs_config.k - len(block_chunks))]
            block_chunks.extend(padding)
            
        # Apply RS across chunks (byte-by-byte for each position)
        # block_chunks is a list of k chunks, each chunk_size bytes
        # We want to produce n - k parity chunks
        
        parity_data = [bytearray() for _ in range(rs_config.num_parity)]
        
        for j in range(chunk_size):
            # Extract byte j from all chunks in block
            byte_slice = bytes([block_chunks[i][j] for i in range(rs_config.k)])
            # Encode with RS
            encoded_slice = rs.encode(byte_slice)
            # The last num_parity bytes are the parity
            for p in range(rs_config.num_parity):
                parity_data[p].append(encoded_slice[rs_config.k + p])
        
        # Add original chunks (from this block) and then the parity chunks
        # Note: we use block_chunks which includes padding for the last block
        all_chunks_with_parity.extend(block_chunks)
        all_chunks_with_parity.extend([bytes(p) for p in parity_data])
        
    return all_chunks_with_parity


def decode_with_rs(chunks_with_erasures: List[bytes | None], rs_config: RSConfig) -> List[bytes]:
    """
    Decode chunks using Reed-Solomon parity.
    
    Args:
        chunks_with_erasures: Chunks where None indicates missing/corrupted
        rs_config: RS(n, k) configuration
    
    Returns:
        Recovered original chunks (without parity)
    """
    if not chunks_with_erasures:
        raise ValueError("chunks list cannot be empty")
    
    chunk_size = None
    for chunk in chunks_with_erasures:
        if chunk is not None:
            chunk_size = len(chunk)
            break
    
    if chunk_size is None:
        raise ValueError("Cannot determine chunk size: all chunks are None")
    
    # Total chunks in pool should be a multiple of rs_config.n
    if len(chunks_with_erasures) % rs_config.n != 0:
        # If not multiple, it might be due to missing trailing chunks or something
        # For Phase 2/3, we assume the list is the full n * num_blocks
        pass

    num_blocks = len(chunks_with_erasures) // rs_config.n
    rs = reedsolo.RSCodec(rs_config.num_parity)
    
    recovered_data_chunks = []
    
    for b in range(num_blocks):
        block_start = b * rs_config.n
        block_chunks = chunks_with_erasures[block_start : block_start + rs_config.n]
        
        # Positions of erasures in this block
        erasures_pos = [i for i, c in enumerate(block_chunks) if c is None]
        
        if len(erasures_pos) > rs_config.num_parity:
            raise ValueError(
                f"Block {b}: Too many erasures ({len(erasures_pos)}) for RS parity ({rs_config.num_parity})"
            )
            
        if not erasures_pos:
            # No erasures in this block, just take the first k
            recovered_data_chunks.extend([c for c in block_chunks[:rs_config.k]])
            continue
            
        # Reconstruct block
        block_recovered = [bytearray(chunk_size) for _ in range(rs_config.k)]
        
        for j in range(chunk_size):
            # Extract byte j from all non-None chunks
            # For reedsolo, we can pass erasures_pos
            # But reedsolo.decode expects the full n bytes with dummy values at erasures
            byte_slice = []
            for i in range(rs_config.n):
                if block_chunks[i] is None:
                    byte_slice.append(0)
                else:
                    byte_slice.append(block_chunks[i][j])
            
            try:
                # Use rs_correct_msg directly as some versions of RSCodec.decode 
                # have different signatures for erasures.
                # rs_correct_msg returns (decoded_msg, decoded_ecc, errata_pos)
                decoded_msg, _, _ = reedsolo.rs_correct_msg(bytes(byte_slice), rs_config.num_parity, erase_pos=erasures_pos)
                for i in range(rs_config.k):
                    block_recovered[i][j] = decoded_msg[i]
            except (reedsolo.ReedSolomonError, TypeError) as e:
                raise ValueError(f"RS decoding failed for block {b} at byte {j}: {e}")
        
        recovered_data_chunks.extend([bytes(c) for c in block_recovered])
        
    return recovered_data_chunks

