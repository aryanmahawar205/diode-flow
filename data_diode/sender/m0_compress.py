"""
sender/m0_compress.py — Streaming File Compression

Compresses input file with lz4 before it enters the pipeline.
Biggest single performance gain for text/log/CSV files (3-5× compression).
Streaming: never loads more than 64MB into RAM — safe for 10GB+ files.

Skip compression for already-compressed formats (jpg, mp4, zip, etc.)
to avoid wasting CPU and making them larger.
"""

import hashlib
import os
import lz4.frame
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SKIP_COMPRESSION_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
    '.mp4', '.mkv', '.avi', '.mov', '.wmv',
    '.zip', '.gz', '.bz2', '.7z', '.rar', '.lz4', '.zst',
    '.mp3', '.aac', '.flac', '.ogg',
    '.pdf',   # already internally compressed
}

BLOCK_SIZE = 64 * 1024 * 1024   # 64MB — fast, RAM-safe


@dataclass
class CompressionResult:
    compressed_path   : str
    original_size     : int
    compressed_size   : int
    compression_ratio : float    # original / compressed
    algorithm         : str      # "lz4" or "none"
    original_sha256   : str      # SHA-256 of original file (pre-compression)
    compressed_sha256 : str      # SHA-256 of compressed file (in-transit integrity)


def should_compress(file_path: str) -> bool:
    ext = Path(file_path).suffix.lower()
    return ext not in SKIP_COMPRESSION_EXTENSIONS


def compute_sha256_streaming(file_path: str) -> str:
    """Compute SHA-256 of any size file without loading it into RAM."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            block = f.read(65536)   # 64KB blocks
            if not block:
                break
            sha256.update(block)
    return sha256.hexdigest()


def compress_file(input_path: str, output_path: str) -> CompressionResult:
    """
    Compress file using lz4 streaming.
    If file type should not be compressed, copies as-is with algorithm="none".
    """
    original_size   = os.path.getsize(input_path)
    original_sha256 = compute_sha256_streaming(input_path)

    if not should_compress(input_path):
        # Copy as-is — no compression benefit
        import shutil
        shutil.copy2(input_path, output_path)
        compressed_sha256 = original_sha256
        return CompressionResult(
            compressed_path   = output_path,
            original_size     = original_size,
            compressed_size   = original_size,
            compression_ratio = 1.0,
            algorithm         = "none",
            original_sha256   = original_sha256,
            compressed_sha256 = compressed_sha256,
        )

    # lz4 streaming compression — 64MB blocks
    with open(input_path, 'rb') as f_in, \
         lz4.frame.open(output_path, 'wb') as f_out:
        while True:
            block = f_in.read(BLOCK_SIZE)
            if not block:
                break
            f_out.write(block)

    compressed_size   = os.path.getsize(output_path)
    compressed_sha256 = compute_sha256_streaming(output_path)
    ratio             = original_size / max(compressed_size, 1)

    logger.info(
        f"Compressed: {original_size / 1024**2:.1f}MB → "
        f"{compressed_size / 1024**2:.1f}MB ({ratio:.1f}× ratio)"
    )

    return CompressionResult(
        compressed_path   = output_path,
        original_size     = original_size,
        compressed_size   = compressed_size,
        compression_ratio = ratio,
        algorithm         = "lz4",
        original_sha256   = original_sha256,
        compressed_sha256 = compressed_sha256,
    )
