"""
Packet validator for received data.
"""

from __future__ import annotations

import logging
import time
import psutil
from dataclasses import dataclass
from typing import Optional
from common.models import TransferManifest

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Result of packet validation."""
    valid: bool
    reason: str = ""


class PacketValidator:
    """Validates received packets against hard limits and manifest."""

    def __init__(
        self,
        max_payload_size: int = 4096,
        max_packet_id: int = 10_000_000,
        max_degree: int = 1024,
    ):
        self.max_payload_size = max_payload_size
        self.max_packet_id = max_packet_id
        self.max_degree = max_degree

    def validate_packet(self, packet: any, manifest: TransferManifest) -> ValidationError:
        """Comprehensive packet validation."""
        # Note: packet is a deserialized EncodedPacket object
        
        # Bounds checks
        if not (0 <= packet.window_id < manifest.total_windows):
            return ValidationError(False, f"window_id {packet.window_id} out of range")
        
        if not (0 <= packet.pass_id < manifest.num_passes):
            return ValidationError(False, f"pass_id {packet.pass_id} out of range")

        if not (0 <= packet.packet_id <= self.max_packet_id):
            return ValidationError(False, f"packet_id {packet.packet_id} out of range")

        if not (1 <= packet.degree <= self.max_degree):
            return ValidationError(False, f"degree {packet.degree} out of range")
        
        if len(packet.chunk_ids) != packet.degree:
            return ValidationError(False, "chunk_ids length mismatch with degree")

        if any(not (0 <= cid < packet.source_chunk_count) for cid in packet.chunk_ids):
            return ValidationError(False, "chunk_id out of range")

        if len(packet.data) > self.max_payload_size:
            return ValidationError(False, f"payload too large: {len(packet.data)}")

        return ValidationError(True)


class ManifestValidator:
    """Validates received manifest against hard limits."""

    MAX_K               = 1_000_000
    MAX_TRANSFER_SIZE   = 100 * 1024**3
    MAX_PASSES          = 2
    MAX_WINDOWS         = 10_000
    MAX_RS_PARITY       = 128

    def validate_manifest_hard_limits(self, manifest: TransferManifest) -> ValidationError:
        """Enforce DoS-prevention hard limits."""
        if manifest.total_chunks > self.MAX_K:
            return ValidationError(False, f"total_chunks {manifest.total_chunks} > MAX_K {self.MAX_K}")
        if manifest.file_size > self.MAX_TRANSFER_SIZE:
            return ValidationError(False, f"file_size exceeds 100GB limit")
        if manifest.num_passes > self.MAX_PASSES:
            return ValidationError(False, f"num_passes {manifest.num_passes} > {self.MAX_PASSES}")
        if manifest.total_windows > self.MAX_WINDOWS:
            return ValidationError(False, f"total_windows {manifest.total_windows} > {self.MAX_WINDOWS}")
        if (manifest.rs_n - manifest.rs_k) > self.MAX_RS_PARITY:
            return ValidationError(False, f"RS parity exceeds limit")
        return ValidationError(True)

    def validate_timestamp(self, timestamp: float, transfer_start: float,
                            max_duration: float = 3600) -> ValidationError:
        """Validate timestamp to prevent extreme replay or future-dated transfers."""
        now = time.time()
        if timestamp < transfer_start - 60:
            return ValidationError(False, "REPLAY: timestamp too old")
        if timestamp > transfer_start + max_duration:
            return ValidationError(False, "REPLAY: timestamp too far in future")
        return ValidationError(True)

    def check_memory_budget(self, manifest: TransferManifest) -> ValidationError:
        """Estimate memory needed for decode and check against available RAM."""
        available_mb = psutil.virtual_memory().available / 1024**2
        # Estimate Tanner graph memory: chunks * size * some_factor
        # A safe estimate is (K_prime * chunk_size * 2)
        K_prime = manifest.total_chunks // manifest.total_windows if manifest.total_windows else manifest.total_chunks
        estimated_mb = (K_prime * manifest.chunk_size * 2) / 1024**2
        if estimated_mb > available_mb * 0.80:
             return ValidationError(False, f"Insufficient RAM: need ~{estimated_mb:.0f}MB, have {available_mb:.0f}MB")
        return ValidationError(True)
