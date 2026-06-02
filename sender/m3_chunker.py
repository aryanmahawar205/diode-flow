"""
Splits window bytes into fixed-size chunks.
Last chunk zero-padded to exactly chunk_size.
Padding length recorded so receiver strips exactly the right bytes.
All output chunks are exactly chunk_size — no exceptions.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ChunkResult:
    chunks          : list[bytes]
    chunk_count     : int
    padding_length  : int
    original_size   : int
    chunk_id_offset : int   # global chunk index of chunks[0]


def chunk_window(window_data: bytes, chunk_size: int,
                 chunk_id_offset: int = 0) -> ChunkResult:
    if not window_data:
        raise ValueError("window_data cannot be empty")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    original_size = len(window_data)
    n_chunks      = (original_size + chunk_size - 1) // chunk_size
    padded_total  = n_chunks * chunk_size
    padding       = padded_total - original_size

    chunks = []
    for i in range(n_chunks):
        s, e = i * chunk_size, (i + 1) * chunk_size
        raw   = window_data[s:min(e, original_size)]
        chunk = raw.ljust(chunk_size, b'\x00')   # zero-pad last chunk
        chunks.append(chunk)

    assert all(len(c) == chunk_size for c in chunks)

    return ChunkResult(chunks=chunks, chunk_count=n_chunks,
                       padding_length=padding, original_size=original_size,
                       chunk_id_offset=chunk_id_offset)
