"""
Streams window temp files into final output file.
Never loads whole file into RAM — 64MB blocks.
Computes SHA-256 streaming during assembly.
Deletes each temp file as it's consumed.
"""
from __future__ import annotations
import hashlib
import hmac
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BLOCK = 64 * 1024 * 1024   # 64MB read blocks


def assemble(window_files: dict[int, Path], total_windows: int,
             output_path: Path, expected_sha256: str) -> bool:
    """
    Concatenate window files in order → output_path.
    Returns True if assembly succeeds and SHA-256 matches.
    """
    sha256 = hashlib.sha256()

    try:
        with open(output_path, 'wb') as out:
            for wid in range(total_windows):
                path = window_files.get(wid)
                if path is None or not path.exists():
                    logger.error(f"Window {wid} file missing")
                    return False
                with open(path, 'rb') as wf:
                    while chunk := wf.read(BLOCK):
                        out.write(chunk)
                        sha256.update(chunk)
                path.unlink()   # delete temp file immediately
    except Exception as e:
        logger.error(f"Assembly error: {e}")
        return False

    actual = sha256.hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        logger.error(f"SHA-256 mismatch after assembly")
        return False

    logger.info(f"Assembled: {output_path} ({output_path.stat().st_size/1024**2:.1f}MB)")
    return True
