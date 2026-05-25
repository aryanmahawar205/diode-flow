"""
receiver/m24_decompress.py — Streaming Decompression

Decompresses lz4 file after all integrity checks pass.
Streaming: safe for 10GB+ files. Never loads whole file into RAM.
Verifies decompressed result against original_sha256 from manifest.
"""

import hashlib
import hmac
import lz4.frame
import logging
import os

logger = logging.getLogger(__name__)

BLOCK_SIZE = 64 * 1024 * 1024   # 64MB read blocks


def decompress_file(
    compressed_path : str,
    output_path     : str,
    algorithm       : str,    # manifest.compression_algorithm
    expected_sha256 : str,    # manifest.original_sha256
) -> bool:
    """
    Decompress and verify.
    Returns True on success. Returns False (never raises) on any failure.
    """
    if algorithm == "none":
        import shutil
        shutil.copy2(compressed_path, output_path)
        actual = _sha256_streaming(output_path)
        if not hmac.compare_digest(actual, expected_sha256):
            logger.error("SHA-256 mismatch on uncompressed file")
            return False
        return True

    if algorithm != "lz4":
        logger.error(f"Unknown compression algorithm: {algorithm}")
        return False

    sha256 = hashlib.sha256()
    try:
        with lz4.frame.open(compressed_path, 'rb') as f_in, \
             open(output_path, 'wb') as f_out:
            while True:
                block = f_in.read(BLOCK_SIZE)
                if not block:
                    break
                f_out.write(block)
                sha256.update(block)
    except Exception as e:
        logger.error(f"Decompression failed: {e}")
        return False

    actual = sha256.hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        logger.error("Decompressed SHA-256 mismatch — file corrupted in transit")
        return False

    os.remove(compressed_path)
    logger.info(f"Decompressed and verified: {output_path}")
    return True


def _sha256_streaming(path: str) -> str:
    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            block = f.read(65536)
            if not block:
                break
            sha256.update(block)
    return sha256.hexdigest()
