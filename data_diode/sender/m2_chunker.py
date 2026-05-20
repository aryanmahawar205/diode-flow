"""
File analyzer and chunker for a single window.

This module reads a window of bytes from a file and splits it into fixed-size
chunks. The last chunk is zero-padded to exact chunk_size. Padding length is
recorded so the receiver can strip it.

Why separate from m1_windowing?
- Windowing handles the file-level division (logical boundaries).
- Chunking handles the chunk-level encoding prep (physical encoding units).
- Separation allows m2_chunker to be testable in isolation.

Design decisions:
- All chunks are exactly chunk_size bytes (enforced by padding).
- Padding is always applied to the last chunk (simplifies receiver logic).
- Chunk IDs are global, not per-window (allows cross-check detection).
- Returns both chunks and metadata for receiver verification.

Invariant: All output chunks have len(chunk) == chunk_size.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ChunkerResult:
    """
    Output of file chunking operation.

    Attributes:
        chunks: list[bytes] of exactly chunk_size each.
        chunk_count: Number of chunks (length of chunks list).
        padding_length: Bytes of zero-padding added to last chunk (receiver removes).
        original_window_size: Actual bytes from input (before padding).
    """
    chunks: list[bytes]
    chunk_count: int
    padding_length: int
    original_window_size: int


def chunk_window(
    window_data: bytes,
    chunk_size: int,
) -> ChunkerResult:
    """
    Split window data into fixed-size chunks with zero-padding.

    Parameters:
        window_data: Bytes to chunk (raw file content, no padding yet).
        chunk_size: Target chunk size (bytes).

    Returns:
        ChunkerResult with chunks, padding_length, etc.

    Raises:
        ValueError: if window_data empty, chunk_size invalid, or data too large.

    Example:
        >>> result = chunk_window(b"hello_world", chunk_size=5)
        >>> len(result.chunks)
        3
        >>> len(result.chunks[0])
        5
        >>> result.padding_length
        4  # last chunk was "world" (5 bytes) + 4 zeros = 9 total
    """
    if not window_data:
        raise ValueError("window_data cannot be empty")

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    if chunk_size > 1024 * 1024:  # arbitrary safety limit
        raise ValueError(f"chunk_size too large: {chunk_size}")

    original_size = len(window_data)

    # Compute how many chunks we need
    chunk_count = (original_size + chunk_size - 1) // chunk_size

    # Compute padding needed
    total_size_padded = chunk_count * chunk_size
    padding_length = total_size_padded - original_size

    logger.debug(
        f"Chunking window: {original_size} bytes into {chunk_count} chunks "
        f"({chunk_size} bytes each), padding={padding_length}"
    )

    # Split into chunks
    chunks = []
    for i in range(chunk_count):
        start = i * chunk_size
        end = start + chunk_size

        # Extract chunk data
        if end <= original_size:
            # Full chunk from original data
            chunk = window_data[start:end]
        else:
            # Last chunk: data from original + zero-padding
            chunk = window_data[start:original_size]
            chunk = chunk.ljust(chunk_size, b'\x00')

        chunks.append(chunk)

    # Verify all chunks are exactly chunk_size
    for i, chunk in enumerate(chunks):
        if len(chunk) != chunk_size:
            raise ValueError(
                f"Chunk {i} has size {len(chunk)}, expected {chunk_size}"
            )

    return ChunkerResult(
        chunks=chunks,
        chunk_count=chunk_count,
        padding_length=padding_length,
        original_window_size=original_size,
    )


def analyze_file(file_path: str, chunk_size: int) -> int:
    """
    Analyze a file to determine chunk count without loading it.

    Parameters:
        file_path: Path to file.
        chunk_size: Target chunk size.

    Returns:
        Number of chunks needed.

    Raises:
        FileNotFoundError: if file doesn't exist.
        ValueError: if chunk_size invalid.
    """
    import os

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    file_size = os.path.getsize(file_path)
    chunk_count = (file_size + chunk_size - 1) // chunk_size

    logger.debug(f"File {file_path}: {file_size} bytes → {chunk_count} chunks")

    return chunk_count
