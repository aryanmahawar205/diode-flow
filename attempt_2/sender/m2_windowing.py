"""
Divides a file into fixed-size windows.
Small files (< 64MB) become a single window — zero windowing overhead.
Large files get windows that fit within RAM budget for the Tanner graph.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
from common.config import get_window_size

logger = logging.getLogger(__name__)

@dataclass
class Window:
    window_id  : int
    start_byte : int
    end_byte   : int
    num_bytes  : int
    is_last    : bool

    def __post_init__(self):
        assert self.num_bytes == self.end_byte - self.start_byte


def compute_windows(file_size: int, window_size: int) -> list[Window]:
    windows, wid, offset = [], 0, 0
    while offset < file_size:
        end   = min(offset + window_size, file_size)
        windows.append(Window(wid, offset, end, end - offset, end >= file_size))
        offset, wid = end, wid + 1
    logger.debug(f"File {file_size/1024**2:.1f}MB → {len(windows)} windows "
                 f"(window_size={window_size/1024**2:.0f}MB)")
    return windows


def read_window(file_path: Path, window: Window) -> bytes:
    with open(file_path, 'rb') as f:
        f.seek(window.start_byte)
        data = f.read(window.num_bytes)
    if len(data) != window.num_bytes:
        raise IOError(f"Short read on window {window.window_id}")
    return data
