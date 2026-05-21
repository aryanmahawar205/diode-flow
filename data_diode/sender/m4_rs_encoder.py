"""
sender/m4_rs_encoder.py — Reed-Solomon Encoder (Phase 2 Simplified)

Role:
Adds Reed-Solomon parity chunks to each window's chunk list before fountain
encoding. Creates a second recovery layer at the chunk level.

Design (Phase 2 simplified):
- In Phase 2, RS is a placeholder for demonstrating architecture
- Real RS implementation deferred to Phase 3+
- Current version: adds "parity chunks" that are duplicates of data chunks
- Receiver can use these duplicates for gap filling if fountain decode insufficient

Note on RS:
Reed-Solomon can recover from chunk loss, complementing fountain's packet recovery.
With real RS(32,6), can recover up to 6 missing chunks per 32-chunk block.
Phase 2 uses simplified duplication; Phase 3 implements cryptographic RS.
"""

from dataclasses import dataclass
from typing import List


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
    
    Args:
        config_str: Format "RS(n,k)" where n and k are integers
    
    Returns:
        RSConfig with n and k
    
    Raises:
        ValueError: If format invalid
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
    Encode chunks with Reed-Solomon parity (Phase 2 simplified).
    
    Phase 2: Returns original chunks + duplicated parity chunks
    Real RS will be implemented in Phase 3+
    
    Args:
        chunks: List of chunks (all must be same size)
        rs_config: RS(n, k) configuration
    
    Returns:
        Original chunks + parity chunks appended
    
    Raises:
        ValueError: If chunks list empty or mismatched sizes
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")
    
    # Verify all chunks same size
    chunk_size = len(chunks[0])
    for i, chunk in enumerate(chunks):
        if len(chunk) != chunk_size:
            raise ValueError(f"Chunk {i} has size {len(chunk)}, expected {chunk_size}")
    
    K = len(chunks)  # number of data chunks
    
    # Validate chunk count is compatible with RS
    if K > rs_config.k:
        raise ValueError(
            f"Have {K} data chunks but RS config is RS({rs_config.n}, {rs_config.k}) "
            f"(max {rs_config.k} data chunks per block)"
        )
    
    # Pad to rs_config.k if needed
    if K < rs_config.k:
        fill_chunk = b"\x00" * chunk_size
        chunks = chunks + [fill_chunk for _ in range(rs_config.k - K)]

    # Phase 2 simplified: duplicate last chunk for parity
    # Phase 3 will use real RS encoding
    parity_chunks = [chunks[-1] for _ in range(rs_config.num_parity)]
    
    result = chunks + parity_chunks
    return result


def decode_with_rs(chunks_with_erasures: List[bytes | None], rs_config: RSConfig) -> List[bytes]:
    """
    Decode chunks using Reed-Solomon parity (Phase 2 simplified).
    
    Phase 2: Uses first available chunk to fill gaps
    Phase 3+ will use actual RS decoding
    
    Args:
        chunks_with_erasures: Chunks where None indicates missing/corrupted
        rs_config: RS(n, k) configuration
    
    Returns:
        Recovered original chunks (without parity)
    
    Raises:
        ValueError: If too many erasures or all chunks missing
    """
    if not chunks_with_erasures:
        raise ValueError("chunks list cannot be empty")
    
    # Find chunk size from non-None entries
    chunk_size = None
    for chunk in chunks_with_erasures:
        if chunk is not None:
            chunk_size = len(chunk)
            break
    
    if chunk_size is None:
        raise ValueError("Cannot determine chunk size: all chunks are None")
    
    # Count erasures
    erasure_count = sum(1 for c in chunks_with_erasures if c is None)
    
    if erasure_count > rs_config.num_parity:
        raise ValueError(
            f"Too many erasures ({erasure_count}) for RS parity ({rs_config.num_parity})"
        )
    
    K = len(chunks_with_erasures) - rs_config.num_parity
    
    # Phase 2 simplified: find first good chunk, use to fill gaps
    fill_chunk = None
    for i, chunk in enumerate(chunks_with_erasures):
        if chunk is not None:
            fill_chunk = chunk
            break
    
    if fill_chunk is None:
        raise ValueError("Cannot decode: no chunks present")
    
    # Return original K chunks, filling gaps
    result = []
    for i in range(K):
        if i < len(chunks_with_erasures) and chunks_with_erasures[i] is not None:
            result.append(chunks_with_erasures[i])
        else:
            # Use available chunk as fallback
            result.append(fill_chunk)
    
    return result
