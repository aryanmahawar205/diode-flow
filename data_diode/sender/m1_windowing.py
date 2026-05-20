"""
sender/m1_windowing.py — File Windowing Engine

Role:
Divides large files into fixed-size windows so each window can be independently
encoded, transmitted, and decoded with bounded memory usage.

Design:
- Input: file path, window_size_bytes
- Output: list[Window] where each Window contains a range [start_byte, end_byte)
- Each window is self-contained:
  * Own chunk set
  * Own Merkle subtree (rolled up to global Merkle tree)
  * Own RS encoding session
  * Own fountain encode session(s)
  * Own decode session on receiver
  
- Global Merkle tree is hierarchical: window Merkle roots are children of the
  global root. This preserves end-to-end integrity while enabling windowed
  processing.

Why windowing?
- A 10 GB file at 1200-byte chunks = ~8.7 million chunks
- A Tanner graph with 8.7M nodes exhausts RAM
- Windows bound the graph to ~50-100k chunks per window (manageable)
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Window:
    """Represents one logical window of a file."""
    window_id: int          # 0-based window index
    start_byte: int         # Inclusive start offset in file
    end_byte: int           # Exclusive end offset in file
    num_bytes: int          # = end_byte - start_byte
    is_last: bool           # True if this is the final window
    
    def __post_init__(self):
        """Validate window invariants."""
        if self.start_byte >= self.end_byte:
            raise ValueError(f"Invalid window range: [{self.start_byte}, {self.end_byte})")
        if self.num_bytes != self.end_byte - self.start_byte:
            raise ValueError(f"num_bytes mismatch: {self.num_bytes} != {self.end_byte - self.start_byte}")


def compute_windows(file_size_bytes: int, window_size_bytes: int) -> list[Window]:
    """
    Divide a file into windows.
    
    Args:
        file_size_bytes: Total file size
        window_size_bytes: Bytes per window
    
    Returns:
        list[Window] in order, with is_last set correctly
    """
    if file_size_bytes <= 0:
        raise ValueError(f"file_size_bytes must be > 0, got {file_size_bytes}")
    if window_size_bytes <= 0:
        raise ValueError(f"window_size_bytes must be > 0, got {window_size_bytes}")
    
    windows = []
    window_id = 0
    offset = 0
    
    while offset < file_size_bytes:
        end = min(offset + window_size_bytes, file_size_bytes)
        num_bytes = end - offset
        is_last = (end >= file_size_bytes)
        
        window = Window(
            window_id=window_id,
            start_byte=offset,
            end_byte=end,
            num_bytes=num_bytes,
            is_last=is_last,
        )
        windows.append(window)
        
        offset = end
        window_id += 1
    
    return windows


def get_file_window(file_path: Path, window: Window) -> bytes:
    """
    Read one window from a file.
    
    Args:
        file_path: Path to file
        window: Window descriptor
    
    Returns:
        bytes of exactly window.num_bytes
    
    Raises:
        IOError: If file cannot be read or is too short
    """
    with open(file_path, "rb") as f:
        f.seek(window.start_byte)
        data = f.read(window.num_bytes)
    
    if len(data) != window.num_bytes:
        raise IOError(
            f"Failed to read window {window.window_id}: "
            f"expected {window.num_bytes} bytes, got {len(data)}"
        )
    
    return data
