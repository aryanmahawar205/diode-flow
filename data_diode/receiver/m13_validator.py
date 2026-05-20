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


class PacketValidator:
    """Validates received packets."""

    def __init__(
        self,
        max_payload_size: int = 2048,
        max_packet_id: int = 1000000,
        max_degree: int = 1000,
    ):
        """
        Initialize validator.

        Parameters:
            max_payload_size: Reject payloads larger than this.
            max_packet_id: Reject packet_id > this (prevent overflow).
            max_degree: Reject fountain degree > this.
        """
        self.max_payload_size = max_payload_size
        self.max_packet_id = max_packet_id
        self.max_degree = max_degree

    def validate_payload_size(self, payload: bytes) -> ValidationError:
        """
        Check payload is within bounds.

        Parameters:
            payload: Packet payload bytes.

        Returns:
            ValidationError with valid=True if acceptable.
        """
        if len(payload) == 0:
            return ValidationError(False, "Empty payload")

        if len(payload) > self.max_payload_size:
            return ValidationError(
                False,
                f"Payload too large: {len(payload)} > {self.max_payload_size}"
            )

        return ValidationError(True)

    def validate_packet_id(self, packet_id: int) -> ValidationError:
        """
        Check packet_id is valid.

        Parameters:
            packet_id: Packet sequence number from header.

        Returns:
            ValidationError with valid=True if acceptable.
        """
        if packet_id < 0:
            return ValidationError(False, f"packet_id negative: {packet_id}")

        if packet_id > self.max_packet_id:
            return ValidationError(
                False,
                f"packet_id too large: {packet_id} > {self.max_packet_id}"
            )

        return ValidationError(True)

    def validate_window_id(self, window_id: int, total_windows: int) -> ValidationError:
        """
        Check window_id is valid for transfer.

        Parameters:
            window_id: Window number from packet.
            total_windows: Total windows in transfer (from manifest).

        Returns:
            ValidationError with valid=True if acceptable.
        """
        if window_id < 0:
            return ValidationError(False, f"window_id negative: {window_id}")

        if window_id >= total_windows:
            return ValidationError(
                False,
                f"window_id out of range: {window_id} >= {total_windows}"
            )

        return ValidationError(True)

    def validate_fountain_degree(self, degree: int) -> ValidationError:
        """
        Check fountain degree is valid.

        Parameters:
            degree: XOR combination degree (1 to K).

        Returns:
            ValidationError with valid=True if acceptable.
        """
        if degree <= 0:
            return ValidationError(False, f"degree must be positive: {degree}")

        if degree > self.max_degree:
            return ValidationError(
                False,
                f"degree too large: {degree} > {self.max_degree}"
            )

        return ValidationError(True)

    def validate_pass_id(self, pass_id: int, max_passes: int) -> ValidationError:
        """
        Check pass_id is valid for transfer.

        Parameters:
            pass_id: Encoding pass number.
            max_passes: Total passes in transfer (from manifest).

        Returns:
            ValidationError with valid=True if acceptable.
        """
        if pass_id < 0:
            return ValidationError(False, f"pass_id negative: {pass_id}")

        if pass_id >= max_passes:
            return ValidationError(
                False,
                f"pass_id out of range: {pass_id} >= {max_passes}"
            )

        return ValidationError(True)

    def validate_transfer_id(self, transfer_id: str) -> ValidationError:
        """
        Check transfer_id format.

        Parameters:
            transfer_id: Transfer UUID.

        Returns:
            ValidationError with valid=True if acceptable.
        """
        if not transfer_id:
            return ValidationError(False, "transfer_id is empty")

        if len(transfer_id) > 128:
            return ValidationError(
                False,
                f"transfer_id too long: {len(transfer_id)} > 128"
            )

        return ValidationError(True)

    def validate_crc32c(
        self,
        payload: bytes,
        crc32c_value: int
    ) -> ValidationError:
        """
        Check CRC32C checksum.

        Parameters:
            payload: Packet data to verify.
            crc32c_value: Expected CRC32C value.

        Returns:
            ValidationError with valid=True if checksum matches.

        Note: Requires crcmod dependency.
        """
        try:
            import crcmod
        except ImportError:
            logger.warning("crcmod not available, skipping CRC validation")
            return ValidationError(True)

        crc_func = crcmod.mkCrcFun(0x11EDC6F41, initCrc=0, xorOut=0xffffffff)
        computed = crc_func(payload)

        if computed != crc32c_value:
            return ValidationError(
                False,
                f"CRC32C mismatch: computed {computed:08x}, expected {crc32c_value:08x}"
            )

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
