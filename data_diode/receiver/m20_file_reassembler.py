"""
receiver/m20_file_reassembler.py — Disk-Based Streaming Assembly

Concatenates window temp files into the final assembled file.
Uses streaming (64MB blocks) to avoid loading whole file into RAM.
Computes SHA-256 during assembly for efficient integrity check.
"""

import hashlib
import hmac
import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

READ_BLOCK = 64 * 1024 * 1024  # 64MB buffer for streaming assembly


class FileReassembler:
    """
    Assembles multiple window files into a single final file on disk.
    """

    def streaming_assemble(
        self,
        window_files     : Dict[int, Path],
        total_windows    : int,
        output_path      : Path,
        expected_sha256  : str,
    ) -> bool:
        """
        Concatenate window files in order and verify SHA-256.
        Returns True on success.
        """
        if len(window_files) != total_windows:
            logger.error(f"Missing windows: have {len(window_files)}, expected {total_windows}")
            return False

        sha256 = hashlib.sha256()
        
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as out:
                for window_id in range(total_windows):
                    path = window_files.get(window_id)
                    if path is None or not path.exists():
                        logger.error(f"Window file {window_id} missing or invalid")
                        return False
                    
                    with open(path, 'rb') as wf:
                        while True:
                            block = wf.read(READ_BLOCK)
                            if not block:
                                break
                            out.write(block)
                            sha256.update(block)
                    
                    # Delete window temp file after successful read
                    path.unlink()
            
            actual_sha256 = sha256.hexdigest()
            if not hmac.compare_digest(actual_sha256, expected_sha256):
                logger.error(f"SHA-256 mismatch on assembled file: {actual_sha256} != {expected_sha256}")
                return False
            
            logger.info(f"Successfully assembled file: {output_path} ({os.path.getsize(output_path)} bytes)")
            return True
            
        except Exception as e:
            logger.error(f"Streaming assembly failed: {e}")
            return False

    def assemble_window_data(self, chunks: list[bytes], padding_length: int = 0) -> bytes:
        """
        Combine chunks for a single window into bytes.
        Strips padding from the last chunk.
        """
        if not chunks:
            return b""
            
        window_data = bytearray()
        for i, chunk in enumerate(chunks):
            if i == len(chunks) - 1 and padding_length > 0:
                window_data.extend(chunk[:-padding_length])
            else:
                window_data.extend(chunk)
        return bytes(window_data)
