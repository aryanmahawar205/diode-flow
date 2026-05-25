"""
Streaming file compression using lz4.
NEVER loads the whole file — reads 64MB at a time.
Safe for 10GB+ files on 8GB RAM systems.
Skips compression for already-compressed formats (jpg, mp4, zip).
"""
from __future__ import annotations
import hashlib
import logging
import os
import shutil
from pathlib import Path
import lz4.frame
from common.models import CompressionResult

logger  = logging.getLogger(__name__)
BLOCK   = 64 * 1024 * 1024   # 64MB read blocks
SKIP_EXT = {'.jpg','.jpeg','.png','.gif','.webp','.bmp',
            '.mp4','.mkv','.avi','.mov','.wmv',
            '.zip','.gz','.bz2','.7z','.rar','.lz4','.zst',
            '.mp3','.aac','.flac','.ogg','.pdf'}


def sha256_streaming(path: str) -> str:
    """SHA-256 of any file without loading it into RAM."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def should_compress(path: str) -> bool:
    return Path(path).suffix.lower() not in SKIP_EXT


def compress_file(input_path: str, output_path: str) -> CompressionResult:
    """
    Compress with lz4 streaming. If file type won't benefit, copy as-is.
    Both paths are always populated — caller uses compression_algorithm
    to know whether decompression is needed.
    """
    original_size   = os.path.getsize(input_path)
    original_sha256 = sha256_streaming(input_path)

    if not should_compress(input_path):
        shutil.copy2(input_path, output_path)
        return CompressionResult(
            compressed_path=output_path, original_size=original_size,
            compressed_size=original_size, compression_ratio=1.0,
            algorithm="none", original_sha256=original_sha256,
            compressed_sha256=original_sha256)

    with open(input_path, 'rb') as fin, lz4.frame.open(output_path, 'wb') as fout:
        while chunk := fin.read(BLOCK):
            fout.write(chunk)

    compressed_size   = os.path.getsize(output_path)
    compressed_sha256 = sha256_streaming(output_path)
    ratio = original_size / max(compressed_size, 1)

    logger.info(f"Compressed {original_size/1024**2:.1f}MB → "
                f"{compressed_size/1024**2:.1f}MB ({ratio:.2f}x)")

    return CompressionResult(
        compressed_path=output_path, original_size=original_size,
        compressed_size=compressed_size, compression_ratio=ratio,
        algorithm="lz4", original_sha256=original_sha256,
        compressed_sha256=compressed_sha256)
