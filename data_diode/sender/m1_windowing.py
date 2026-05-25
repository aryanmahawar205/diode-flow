"""
sender/m1_windowing.py — File Windowing Engine
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


def get_window_size_for_file(file_size_bytes: int, profile: any) -> int:
    """
    Proportional window sizing — avoids windowing overhead for small files.

    < 64MB   → single window (no split at all)
    64MB–1GB → 64MB windows (profile default for medium)
    1GB–10GB → 128MB windows (profile default for large)
    > 10GB   → 256MB windows (only if sufficient RAM)
    """
    ONE_MB = 1024 * 1024
    ONE_GB = 1024 * ONE_MB

    # Handle tiny files
    if file_size_bytes <= 0:
        return 1024

    if file_size_bytes < 64 * ONE_MB:
        return file_size_bytes      # single window, zero split overhead

    if file_size_bytes < ONE_GB:
        return 64 * ONE_MB

    if file_size_bytes < 10 * ONE_GB:
        return 128 * ONE_MB

    return 256 * ONE_MB             # > 10GB — requires high-RAM system


def compute_windows(file_size_bytes: int, window_size_bytes: int) -> list[Window]:
    """
    Divide a file into windows.
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
