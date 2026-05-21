"""
receiver/m19_window_reassembler.py — Window-Level Reassembly

Role:
Reassemble chunks within a window after decoding and verification. Coordinates
with Merkle verifier to identify corrupted chunks, triggers RS recovery for gaps,
and combines windows back into complete file.

Design:
1. Input: decoded chunks (some may be None if decode failed)
2. Verify chunk Merkle proofs (mark corrupted as failed)
3. If gaps remain, attempt RS decoding
4. Output: complete window bytes
5. Combine windows → final file
"""

from typing import List, Optional, Tuple
from pathlib import Path


class WindowReassembler:
    """Reassembles a single window from decoded chunks."""
    
    def __init__(self, window_id: int, chunk_size: int, expected_bytes: int):
        """
        Initialize window reassembler.
        
        Args:
            window_id: Window index
            chunk_size: Bytes per chunk
            expected_bytes: Expected window size (for last window, may be < chunk_size * chunk_count)
        """
        self.window_id = window_id
        self.chunk_size = chunk_size
        self.expected_bytes = expected_bytes
        self.chunks: dict[int, bytes] = {}
        self.failed_chunks: set[int] = set()
    
    def add_chunk(self, chunk_id: int, chunk_data: bytes) -> None:
        """Add a decoded chunk to window."""
        if chunk_data is not None:
            self.chunks[chunk_id] = chunk_data
    
    def mark_failed(self, chunk_id: int) -> None:
        """Mark a chunk as failed (corrupted or still missing)."""
        self.failed_chunks.add(chunk_id)
        self.chunks.pop(chunk_id, None)
    
    def get_window_bytes(self, padding_length: int = 0) -> Optional[bytes]:
        """
        Reassemble window into contiguous bytes.
        
        Args:
            padding_length: Number of trailing zero bytes to remove (for last chunk)
        
        Returns:
            Reassembled bytes if complete, None if gaps remain
        """
        if self.failed_chunks:
            # Gaps still exist
            return None
        
        # Check we have expected chunk count
        num_chunks = (self.expected_bytes + self.chunk_size - 1) // self.chunk_size
        if len(self.chunks) < num_chunks:
            return None
        
        # Concatenate chunks in order
        result = b""
        for i in range(num_chunks):
            if i not in self.chunks:
                return None  # Still missing chunks
            result += self.chunks[i]
        
        # Remove padding if this is last window
        if padding_length > 0:
            result = result[:-padding_length]
        
        # Trim to expected size
        if len(result) > self.expected_bytes:
            result = result[:self.expected_bytes]
        
        return result
    
    def is_complete(self) -> bool:
        """Check if window is complete and ready for output."""
        if self.failed_chunks:
            return False
        num_chunks = (self.expected_bytes + self.chunk_size - 1) // self.chunk_size
        return len(self.chunks) == num_chunks


def combine_windows(window_bytes_list: List[bytes]) -> bytes:
    """
    Combine window bytes into complete file.
    
    Args:
        window_bytes_list: List of reassembled window bytes
    
    Returns:
        Concatenated file bytes
    """
    return b"".join(window_bytes_list)


def write_file(output_path: Path, file_bytes: bytes) -> None:
    """
    Write file to disk.
    
    Args:
        output_path: Output file path
        file_bytes: Complete file bytes
    """
    with open(output_path, "wb") as f:
        f.write(file_bytes)
