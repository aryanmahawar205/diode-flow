"""
receiver/m24_decompress.py — File Decompression

Role:
Decompresses the reconstructed file after all integrity checks pass.
"""

from __future__ import annotations
import lz4.frame
import os
import hashlib
import logging
import hmac

logger = logging.getLogger(__name__)

def decompress_file(
    compressed_path : str,
    output_path     : str,
    algorithm       : str,    # from manifest.compression_algorithm
    expected_sha256 : str,    # manifest.original_sha256
) -> bool:
    """
    Decompress file and verify against original SHA-256.
    """
    if not os.path.exists(compressed_path):
        logger.error(f"Compressed file not found: {compressed_path}")
        return False

    try:
        if algorithm == "none":
            # Just copy or hash and move
            sha256 = hashlib.sha256()
            with open(compressed_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    while True:
                        chunk = f_in.read(1024 * 1024)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        sha256.update(chunk)
            
            actual_hash = sha256.hexdigest()
        elif algorithm == "lz4":
            sha256 = hashlib.sha256()
            with open(compressed_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    with lz4.frame.LZ4FrameDecompressor() as decompressor:
                        while True:
                            chunk = f_in.read(1024 * 1024)
                            if not chunk:
                                break
                            
                            # lz4.frame.decompress can return multiple chunks
                            # from one input block if it contains multiple frames
                            # but usually we just call it repeatedly.
                            # Actually decompressor.decompress returns bytes.
                            decompressed = decompressor.decompress(chunk)
                            if decompressed:
                                f_out.write(decompressed)
                                sha256.update(decompressed)
            
            actual_hash = sha256.hexdigest()
        else:
            logger.error(f"Unsupported compression algorithm: {algorithm}")
            return False

        # Verify hash
        if not hmac.compare_digest(actual_hash, expected_sha256):
            logger.error(f"Decompressed file hash mismatch: expected {expected_sha256}, got {actual_hash}")
            return False

        return True
    except Exception as e:
        logger.error(f"Decompression failed: {e}")
        return False
