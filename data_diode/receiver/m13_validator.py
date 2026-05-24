"""
Packet validator for received data.

Step 14 of Phase 1: receiver/m13_validator.py

Validates received packets for format, integrity, and bounds.
Catches malformed packets before they reach the decoder.

Key validations:
- CRC32C checksum verification
- Schema validation (field ranges)
- Bounds checking (prevents DoS via oversized fields)
- Transfer metadata validation (transfer_id, window_id match manifest)

Design philosophy:
- Fail fast: Reject bad packets immediately
- Strict mode: Conservative bounds checking
- Logging: Log all rejections for debugging
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Result of packet validation."""
    valid: bool
    reason: str = ""


import time

class PacketValidator:
    """Validates received packets against hard limits and manifest."""

    def __init__(
        self,
        max_payload_size: int = 1500,
        max_packet_id: int = 1000000,
        max_degree: int = 512,
        max_chunk_ids: int = 512,
    ):
        """
        Initialize validator with hard limits.
        """
        self.max_payload_size = max_payload_size
        self.max_packet_id = max_packet_id
        self.max_degree = max_degree
        self.max_chunk_ids = max_chunk_ids
        self.seen_timestamps = {} # transfer_id -> last_timestamp

    def validate_packet(self, packet: any, manifest: any) -> ValidationError:
        """
        Comprehensive packet validation.
        """
        # Transfer ID match
        if packet.transfer_id != manifest.transfer_id:
            return ValidationError(False, "transfer_id mismatch")

        # Bounds checks
        if not (0 <= packet.window_id < manifest.total_windows):
            return ValidationError(False, f"window_id {packet.window_id} out of range")
        
        if not (0 <= packet.pass_id < manifest.num_passes):
            return ValidationError(False, f"pass_id {packet.pass_id} out of range")

        if not (0 <= packet.packet_id <= self.max_packet_id):
            return ValidationError(False, f"packet_id {packet.packet_id} out of range")

        if not (1 <= packet.fountain_degree <= self.max_degree):
            return ValidationError(False, f"degree {packet.fountain_degree} out of range")
        
        if len(packet.chunk_ids) != packet.fountain_degree:
            return ValidationError(False, "chunk_ids length mismatch with degree")

        if any(not (0 <= cid < packet.source_chunk_count) for cid in packet.chunk_ids):
            return ValidationError(False, "chunk_id out of range")

        if len(packet.payload) > self.max_payload_size:
            return ValidationError(False, f"payload too large: {len(packet.payload)}")

        return ValidationError(True)

    def validate_crc32c(self, payload: bytes, expected_crc: int) -> ValidationError:
        """Verify CRC32C of payload."""
        import crcmod
        crc_func = crcmod.mkCrcFun(0x11EDC6F41, initCrc=0, xorOut=0xffffffff)
        actual_crc = crc_func(payload)
        if actual_crc != expected_crc:
            return ValidationError(False, f"CRC32C mismatch: {actual_crc:08x} != {expected_crc:08x}")
        return ValidationError(True)


class ManifestValidator:
    """Validates received manifest against transfer parameters."""

    def __init__(self, max_file_size: int = 100 * 1024 * 1024):
        """
        Initialize manifest validator.

        Parameters:
            max_file_size: Reject files larger than this.
        """
        self.max_file_size = max_file_size

    def validate_manifest_size_fields(
        self,
        file_size: int,
        chunk_size: int,
        total_chunks: int,
        total_windows: int
    ) -> ValidationError:
        """
        Validate manifest size fields for consistency.

        Parameters:
            file_size: Total bytes in file.
            chunk_size: Bytes per chunk.
            total_chunks: Total chunks across all windows.
            total_windows: Number of windows.

        Returns:
            ValidationError with valid=True if consistent.
        """
        if file_size < 0:
            return ValidationError(False, f"file_size negative: {file_size}")

        if file_size > self.max_file_size:
            return ValidationError(
                False,
                f"file_size too large: {file_size} > {self.max_file_size}"
            )

        if chunk_size <= 0:
            return ValidationError(False, f"chunk_size must be positive: {chunk_size}")

        if total_chunks <= 0:
            return ValidationError(False, f"total_chunks must be positive: {total_chunks}")

        if total_windows <= 0:
            return ValidationError(False, f"total_windows must be positive: {total_windows}")

        # Rough consistency check
        min_chunks = (file_size + chunk_size - 1) // chunk_size
        if total_chunks < min_chunks:
            return ValidationError(
                False,
                f"total_chunks {total_chunks} < min required {min_chunks}"
            )

        return ValidationError(True)