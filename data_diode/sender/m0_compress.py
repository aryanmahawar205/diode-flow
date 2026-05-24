"""
sender/m0_compress.py — File Compression

Role:
Compresses the input file before it enters the pipeline. This is the single
highest-impact performance improvement for large files.
"""

from __future__ import annotations
import lz4.frame
import os
import hashlib
from dataclasses import dataclass

@dataclass
class CompressionResult:
    compressed_path  : str    # path to compressed temp file
    original_size    : int    # bytes before compression
    compressed_size  : int    # bytes after compression
    compression_ratio: float  # original / compressed
    algorithm        : str    # "lz4" or "none"
    original_sha256  : str    # SHA-256 of ORIGINAL file


SKIP_COMPRESSION_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff',
    '.mp4', '.mkv', '.avi', '.mov', '.wmv',
    '.zip', '.gz', '.bz2', '.7z', '.rar', '.lz4',
    '.mp3', '.aac', '.flac', '.pdf'
}


def should_compress(file_path: str) -> bool:
    """Decide whether compression will help based on file extension."""
    _, ext = os.path.splitext(file_path.lower())
    return ext not in SKIP_COMPRESSION_EXTENSIONS


def compress_file(input_path: str, output_path: str, algorithm: str = "lz4") -> CompressionResult:
    """
    Compress file for transfer.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Compute original SHA-256
    sha256 = hashlib.sha256()
    original_size = 0
    with open(input_path, 'rb') as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            sha256.update(chunk)
            original_size += len(chunk)
    
    orig_hash = sha256.hexdigest()

    if algorithm == "none" or not should_compress(input_path):
        # Just copy file to output_path or use it as is if paths same
        if input_path != output_path:
            import shutil
            shutil.copy2(input_path, output_path)
        
        return CompressionResult(
            compressed_path=output_path,
            original_size=original_size,
            compressed_size=original_size,
            compression_ratio=1.0,
            algorithm="none",
            original_sha256=orig_hash
        )

    # Compress with LZ4
    with open(input_path, 'rb') as f_in:
        with open(output_path, 'wb') as f_out:
            # We use a context manager for the frame compressor if available,
            # but lz4.frame.compress is simpler for one-shot.
            # For large files, we should stream it.
            with lz4.frame.LZ4FrameCompressor() as compressor:
                # Header
                f_out.write(compressor.begin())
                while True:
                    chunk = f_in.read(1024 * 1024)
                    if not chunk:
                        break
                    f_out.write(compressor.compress(chunk))
                f_out.write(compressor.flush())

    compressed_size = os.path.getsize(output_path)
    
    return CompressionResult(
        compressed_path=output_path,
        original_size=original_size,
        compressed_size=compressed_size,
        compression_ratio=original_size / compressed_size if compressed_size > 0 else 1.0,
        algorithm="lz4",
        original_sha256=orig_hash
    )
