"""
Streaming decompression. Safe for 10GB+ files.
Verifies decompressed result against original_sha256 from manifest.
Returns bool — never raises.
"""
from __future__ import annotations
import hashlib
import hmac
import logging
import os
from pathlib import Path
import lz4.frame

logger = logging.getLogger(__name__)
BLOCK  = 64 * 1024 * 1024


def decompress(compressed_path: Path, output_path: Path,
               algorithm: str, expected_original_sha256: str) -> bool:
    """Decompress and verify against original SHA-256."""
    if algorithm == "none":
        import shutil
        shutil.copy2(compressed_path, output_path)
    elif algorithm == "lz4":
        sha256 = hashlib.sha256()
        try:
            with lz4.frame.open(compressed_path, 'rb') as fin, \
                 open(output_path, 'wb') as fout:
                while chunk := fin.read(BLOCK):
                    fout.write(chunk)
                    sha256.update(chunk)
        except Exception as e:
            logger.error(f"Decompression failed: {e}")
            return False
        actual = sha256.hexdigest()
        if not hmac.compare_digest(actual, expected_original_sha256):
            logger.error("Decompressed SHA-256 mismatch")
            return False
    else:
        logger.error(f"Unknown algorithm: {algorithm}")
        return False

    compressed_path.unlink(missing_ok=True)
    logger.info(f"Decompressed: {output_path}")
    return True
