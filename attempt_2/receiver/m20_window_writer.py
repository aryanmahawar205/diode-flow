"""
Writes a decoded+verified window to a temp file on disk immediately.
Frees RAM before the next window begins decoding.
Critical for GB-scale files — never hold all windows in RAM.
"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write_window(
    window_id: int,
    chunks: list[bytes | None],
    padding_length: int,
    chunk_count: int,
    chunk_size: int,
    windows_dir: Path
) -> Path | None:
    """
    Reassemble chunks in order, strip padding, write to temp file.
    Returns path on success, None if invalid or incomplete.
    """

    # HARD SAFETY CHECK 1: length mismatch
    if len(chunks) < chunk_count:
        logger.error(
            f"Window {window_id}: chunk list too small "
            f"({len(chunks)} < {chunk_count})"
        )
        return None

    # HARD SAFETY CHECK 2: missing data
    if any(c is None for c in chunks[:chunk_count]):
        missing = [i for i, c in enumerate(chunks[:chunk_count]) if c is None]
        logger.error(
            f"Window {window_id}: {len(missing)} chunks still None — cannot write"
        )
        return None

    temp_path = windows_dir / f"window_{window_id:06d}.bin"

    with open(temp_path, 'wb') as f:
        for i, chunk in enumerate(chunks[:chunk_count]):
            if chunk is None:
                logger.error(f"Window {window_id}: unexpected None at {i}")
                return None

            is_last = (i == chunk_count - 1)

            if is_last and padding_length > 0:
                f.write(chunk[:-padding_length])
            else:
                f.write(chunk)

    logger.info(
        f"WINDOW {window_id} WRITTEN | "
        f"size={temp_path.stat().st_size} "
        f"chunk_count={chunk_count} "
        f"padding={padding_length}"
    )

    return temp_path