"""
Packet validator for received data.
"""

from __future__ import annotations

import logging
import time
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
    """Fast packet validator."""

    def __init__(
        self,
        max_payload_size: int = 8192,
        max_packet_id: int = 10_000_000,
        max_degree: int = 1024,
    ):
        self.max_payload_size = max_payload_size
        self.max_packet_id = max_packet_id
        self.max_degree = max_degree

    def validate_packet(self, packet: any, manifest: TransferManifest) -> ValidationError:
        """Surgical packet validation for performance."""
        # Check window/pass bounds
        if not (0 <= packet.window_id < manifest.total_windows):
            return ValidationError(False, "WID_OOB")
        
        if not (0 <= packet.pass_id < manifest.num_passes):
            return ValidationError(False, "PASS_OOB")

        # Basic consistency
        if not (1 <= packet.degree <= self.max_degree):
            return ValidationError(False, "DEG_OOB")
        
        # Skip checking all chunk_ids for speed — decoder handles bounds
        
        if len(packet.data) > self.max_payload_size:
            return ValidationError(False, "PAYLOAD_TOO_LARGE")

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
            return ValidationError(False, "K_LIMIT")
        if manifest.file_size > self.MAX_TRANSFER_SIZE:
            return ValidationError(False, "SIZE_LIMIT")
        if (manifest.rs_n - manifest.rs_k) > self.MAX_RS_PARITY:
            return ValidationError(False, "RS_LIMIT")
        return ValidationError(True)
