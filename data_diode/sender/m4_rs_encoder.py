"""
sender/m4_rs_encoder.py — Reed-Solomon Encoder

Role:
Adds Reed-Solomon parity chunks to each window's chunk list before fountain
encoding. This creates a second independent recovery layer at the chunk level
(fountain codes recover at the packet level).

Design:
- Input: list of chunks (all exactly chunk_size bytes)
- Config: RS(n, k) — k data chunks, (n-k) parity chunks
- Output: Expanded list with K + (N-K) total chunks
- Encoding is deterministic: same input → same parity

Why RS + Fountain?
- Fountain codes recover from packet loss (UDP layer, probabilistic)
- Reed-Solomon recovers from chunk loss (block layer, deterministic)
- If fountain decode recovers 98% of chunks and 2% missing, RS parity
  reconstructs the remaining 2% deterministically — transfer succeeds

RS configuration from Profile:
  RS(16, 2)   → 2 parity per 16 data chunks (12.5% overhead)
  RS(16, 4)   → 4 parity per 16 data chunks (25% overhead)
  RS(32, 4)   → 4 parity per 32 data chunks (12.5% overhead)
  RS(32, 6)   → 6 parity per 32 data chunks (18.75% overhead)
  RS(32, 8)   → 8 parity per 32 data chunks (25% overhead)
  RS(64, 6)   → 6 parity per 64 data chunks (9.4% overhead)
  RS(64, 8)   → 8 parity per 64 data chunks (12.5% overhead)

Library: reedsolo (RSCodec class)
"""

from dataclasses import dataclass
from typing import Tuple
from reedsolo import RSCodec


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


def encode_with_rs(chunks: list[bytes], rs_config: RSConfig) -> list[bytes]:
    """
    Encode chunks with Reed-Solomon parity.
    
    Algorithm:
    - Split chunks into blocks of size k (data)
    - Encode each block with RSCodec(rs_config.n, rs_config.k)
    - Append parity chunks
    - Flatten and return
    
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
    
    # Create RSCodec for this window
    # reedsolo uses byte-level Galois Field, chunk is treated as array of bytes
    codec = RSCodec(rs_config.num_parity, nsize=256)
    
    # Flatten all chunks into one byte string
    data_bytes = b"".join(chunks)
    
    # Encode: reedsolo returns original + parity bytes
    encoded_bytes = codec.encode(data_bytes)
    
    # Verify encoded_bytes = data_bytes + parity_bytes
    # reedsolo returns (original_data, parity_bytes) encoded into single bytes
    # Actually, RSCodec.encode() returns the encoded message (data + parity)
    # Length should be: data_len + parity_len = K*chunk_size + parity_chunk_size
    
    # Split back into chunks
    total_chunk_count = K + rs_config.num_parity
    parity_chunk_count = rs_config.num_parity
    
    # reedsolo encodes at byte level; we need to preserve chunk boundaries
    # Each parity chunk is chunk_size bytes
    parity_start = K * chunk_size
    parity_bytes = encoded_bytes[parity_start:]
    
    # Split parity into chunks
    parity_chunks = []
    for i in range(parity_chunk_count):
        parity_chunks.append(parity_bytes[i*chunk_size:(i+1)*chunk_size])
    
    # Return original chunks + parity chunks
    result = chunks + parity_chunks
    
    # Sanity check
    if len(result) != total_chunk_count:
        raise RuntimeError(
            f"RS encoding produced {len(result)} chunks, expected {total_chunk_count}"
        )
    
    return result


def decode_with_rs(chunks_with_erasures: list[bytes | None], rs_config: RSConfig) -> list[bytes]:
    """
    Decode chunks using Reed-Solomon parity.
    
    Args:
        chunks_with_erasures: Chunks where None indicates missing/corrupted
        rs_config: RS(n, k) configuration
    
    Returns:
        Recovered original chunks (without parity)
    
    Raises:
        ValueError: If too many erasures or invalid config
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
    
    # Reconstruct full message with None placeholders
    full_bytes = b"".join(c if c is not None else b"\x00" * chunk_size for c in chunks_with_erasures)
    
    # Determine erasure positions
    erasure_positions = [i for i, c in enumerate(chunks_with_erasures) if c is None]
    
    # Decode
    codec = RSCodec(rs_config.num_parity, nsize=256)
    try:
        decoded_bytes = codec.decode(full_bytes, erasure_positions)[0]
    except Exception as e:
        raise ValueError(f"RS decoding failed: {e}")
    
    # Split back into chunks (only the original K data chunks)
    K = len(chunks_with_erasures) - rs_config.num_parity
    result = []
    for i in range(K):
        result.append(decoded_bytes[i*chunk_size:(i+1)*chunk_size])
    
    return result
