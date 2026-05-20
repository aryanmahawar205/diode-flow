"""
File reassembly from decoded chunks.

Step 17 of Phase 1: receiver/m20_file_reassembler.py

Reassembles decoded chunks back into the original file.
Handles padding removal and window reconstruction.

Design:
- Takes decoded chunks (with padding metadata)
- Strips padding from last chunk
- Reconstructs original file bytes
- Validates total size matches manifest
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class FileReassembler:
    """
    Reassembles chunks into a complete file.
    """

    def __init__(self):
        """Initialize file reassembler."""
        self.chunks_buffer = {}  # window_id -> list of chunks

    def add_window_chunks(
        self,
        window_id: int,
        chunks: list[Optional[bytes]],
        chunk_size: int,
        padding_length: int = 0
    ) -> bool:
        """
        Add decoded chunks from a window.

        Parameters:
            window_id: Window number.
            chunks: List of byte strings (may contain None for missing).
            chunk_size: Bytes per chunk (for validation).
            padding_length: Bytes of padding in last chunk (stripped on output).

        Returns:
            True if all chunks present, False if any missing.

        Raises:
            ValueError: if chunks or sizes invalid.
        """
        if not chunks:
            raise ValueError("chunks list is empty")

        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")

        # Check for missing chunks
        has_missing = any(c is None for c in chunks)
        if has_missing:
            logger.warning(f"Window {window_id} has missing chunks")
            return False

        # Validate chunk sizes
        for i, chunk in enumerate(chunks):
            if chunk is None:
                return False

            expected_size = chunk_size
            if i == len(chunks) - 1:
                # Last chunk might be smaller after padding removal
                expected_size = chunk_size  # Still chunk_size before padding removal

            if len(chunk) != expected_size:
                raise ValueError(
                    f"Window {window_id} chunk {i} size mismatch: "
                    f"expected {expected_size}, got {len(chunk)}"
                )

        self.chunks_buffer[window_id] = (chunks, padding_length)
        return True

    def reassemble_file(
        self,
        total_windows: int,
        chunk_size: int,
        expected_file_size: int
    ) -> Optional[bytes]:
        """
        Reassemble complete file from buffered windows.

        Parameters:
            total_windows: Total number of windows.
            chunk_size: Bytes per chunk.
            expected_file_size: Expected output file size (from manifest).

        Returns:
            Complete file bytes, or None if windows missing.

        Raises:
            ValueError: if reassembled size doesn't match expected.
        """
        if len(self.chunks_buffer) != total_windows:
            logger.error(
                f"Missing windows: have {len(self.chunks_buffer)}, "
                f"expected {total_windows}"
            )
            return None

        file_data = bytearray()

        for window_id in range(total_windows):
            if window_id not in self.chunks_buffer:
                logger.error(f"Window {window_id} missing from buffer")
                return None

            chunks, padding_length = self.chunks_buffer[window_id]

            for i, chunk in enumerate(chunks):
                is_last_chunk = (window_id == total_windows - 1) and (i == len(chunks) - 1)

                if is_last_chunk and padding_length > 0:
                    # Remove padding from last chunk
                    file_data.extend(chunk[:-padding_length])
                else:
                    file_data.extend(chunk)

        result = bytes(file_data)

        # Validate size
        if len(result) != expected_file_size:
            raise ValueError(
                f"Reassembled file size mismatch: "
                f"expected {expected_file_size}, got {len(result)}"
            )

        logger.info(f"Reassembled file: {len(result)} bytes")
        return result

    def write_file(self, output_path: str, file_data: bytes) -> None:
        """
        Write reassembled file to disk.

        Parameters:
            output_path: Path to write to.
            file_data: Complete file bytes.

        Raises:
            IOError: if write fails.
        """
        try:
            with open(output_path, "wb") as f:
                f.write(file_data)
            logger.info(f"Wrote {len(file_data)} bytes to {output_path}")
        except IOError as e:
            logger.error(f"Failed to write file: {e}")
            raise

    def clear(self) -> None:
        """Clear buffered chunks."""
        self.chunks_buffer.clear()
