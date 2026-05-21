"""
receiver/m22_quarantine.py — Quarantine pipeline and transfer state machine.

Role:
Manage the quarantine boundary for received transfers.

Design:
- Quarantine files until they pass verification policies
- Reject expired or size/mime mismatched transfers
- Preserve failed transfers for forensic analysis
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from data_diode.common.config import QUARANTINE_DIR, STORAGE_DIR
from data_diode.common.models import TransferManifest

logger = logging.getLogger(__name__)


@dataclass
class QuarantineResult:
    """
    Result of quarantine policy evaluation.
    """
    accepted: bool
    reason: str
    quarantine_path: str | None = None


def _ensure_dir(path: str) -> None:
    """Ensure a directory exists."""
    os.makedirs(path, exist_ok=True)


def _sanitize_filename(file_name: str) -> str:
    """Sanitize filename to avoid directory traversal."""
    return os.path.basename(file_name)


class QuarantineManager:
    """
    Manages quarantine state for received transfers.
    """

    def __init__(self, quarantine_dir: str = QUARANTINE_DIR):
        self.quarantine_dir = quarantine_dir
        _ensure_dir(self.quarantine_dir)

    def quarantine_file(self, file_bytes: bytes, manifest: TransferManifest) -> str:
        """
        Write bytes to quarantine storage.

        Returns:
            Path to quarantine file.
        """
        safe_name = _sanitize_filename(manifest.file_name)
        file_name = f"{manifest.transfer_id}_{safe_name}.quarantine"
        path = os.path.join(self.quarantine_dir, file_name)

        with open(path, "wb") as handle:
            handle.write(file_bytes)

        logger.info("Quarantined file %s", path)
        return path

    def inspect_policy(self, file_bytes: bytes, manifest: TransferManifest) -> QuarantineResult:
        """
        Inspect quarantined file against policy rules.
        """
        if len(file_bytes) != manifest.file_size:
            return QuarantineResult(False, "file_size_mismatch")

        now = time.time()
        if now > manifest.creation_timestamp + manifest.expiration_policy:
            return QuarantineResult(False, "transfer_expired")

        if not manifest.mime_type:
            return QuarantineResult(False, "missing_mime_type")

        # Placeholder for content policy hooks.
        return QuarantineResult(True, "accepted")

    def accept_file(self, file_bytes: bytes, manifest: TransferManifest) -> QuarantineResult:
        """
        Accept a quarantined file and move it to secure storage.
        """
        result = self.inspect_policy(file_bytes, manifest)
        if not result.accepted:
            logger.warning("Quarantine reject: %s", result.reason)
            return result

        # Persist file in secure storage
        storage_path = os.path.join(STORAGE_DIR, f"{manifest.transfer_id}_{_sanitize_filename(manifest.file_name)}")
        _ensure_dir(STORAGE_DIR)

        with open(storage_path, "wb") as handle:
            handle.write(file_bytes)

        result.quarantine_path = storage_path
        logger.info("Accepted file into secure storage: %s", storage_path)
        return result

    def reject_file(self, manifest: TransferManifest, reason: str) -> str:
        """
        Record a rejection event for a transfer.
        """
        logger.error("Rejected transfer %s: %s", manifest.transfer_id, reason)
        return reason
