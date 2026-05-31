"""Streaming lz4 compression. Never loads whole file into RAM."""
from __future__ import annotations
import hashlib
import logging
import os
import shutil
from pathlib import Path
from common.models import CompressionResult

logger = logging.getLogger(__name__)

# File types that don't benefit from compression
SKIP_EXT = {'.jpg','.jpeg','.png','.gif','.mp4','.mkv','.avi','.mov',
            '.zip','.gz','.bz2','.7z','.rar','.lz4','.zst','.mp3',
            '.aac','.flac','.pdf'}

BLOCK = 64 * 1024 * 1024   # 64MB blocks — never load more than this


def sha256_streaming(path: str) -> str:
    """SHA-256 without loading whole file."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def should_compress(path: str) -> bool:
    return Path(path).suffix.lower() not in SKIP_EXT


def compress_file(input_path: str, output_path: str) -> CompressionResult:
    """
    Compress with lz4 streaming. Returns info dict.
    If file type won't compress well, copies as-is (algorithm='none').
    """
    try:
        import lz4.frame
    except ImportError:
        logger.warning("lz4 not installed — skipping compression. Run: pip install lz4")
        shutil.copy2(input_path, output_path)
        sha = sha256_streaming(input_path)
        size = os.path.getsize(input_path)
        return CompressionResult(
            compressed_path=output_path, original_size=size,
            compressed_size=size, compression_ratio=1.0,
            algorithm="none", original_sha256=sha, compressed_sha256=sha)

    original_size   = os.path.getsize(input_path)
    original_sha256 = sha256_streaming(input_path)

    if not should_compress(input_path):
        shutil.copy2(input_path, output_path)
        return CompressionResult(
            compressed_path=output_path, algorithm="none", original_size=original_size,
            compressed_size=original_size, compression_ratio=1.0,
            original_sha256=original_sha256,
            compressed_sha256=original_sha256)

    with open(input_path, 'rb') as fin, lz4.frame.open(output_path, 'wb') as fout:
        while chunk := fin.read(BLOCK):
            fout.write(chunk)

    comp_size   = os.path.getsize(output_path)
    comp_sha256 = sha256_streaming(output_path)
    ratio       = original_size / max(comp_size, 1)

    logger.info(f"Compressed {original_size/1024**2:.1f}MB → "
                f"{comp_size/1024**2:.1f}MB ({ratio:.1f}x ratio)")
    return CompressionResult(
        compressed_path=output_path, algorithm="lz4", original_size=original_size,
        compressed_size=comp_size, compression_ratio=ratio,
        original_sha256=original_sha256, compressed_sha256=comp_sha256)


def decompress_file(compressed_path: str, output_path: str,
               algorithm: str, expected_sha256: str) -> bool:
    """Decompress and verify. Returns True on success. Never raises."""
    try:
        if algorithm == "none":
            shutil.copy2(compressed_path, output_path)
        elif algorithm == "lz4":
            import lz4.frame
            h = hashlib.sha256()
            with lz4.frame.open(compressed_path, 'rb') as fin, \
                 open(output_path, 'wb') as fout:
                while chunk := fin.read(BLOCK):
                    fout.write(chunk)
                    h.update(chunk)
            if h.hexdigest() != expected_sha256:
                logger.error("Decompressed SHA-256 mismatch")
                return False
        else:
            logger.error(f"Unknown algorithm: {algorithm}")
            return False

        os.remove(compressed_path)
        return True
    except Exception as e:
        logger.error(f"Decompression failed: {e}")
        return False
