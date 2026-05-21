"""
receiver/m23_storage.py — Secure storage writer for accepted transfers.

Role:
Atomically persist accepted files and write immutable transfer receipts.

Design:
- Write file atomically using temp file + rename
- Persist JSON receipt alongside accepted file
- Enforce secure filesystem permissions
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from common.config import STORAGE_DIR, STORAGE_DIR_PERMISSIONS
from common.models import TransferManifest

logger = logging.getLogger(__name__)


@dataclass
class StorageReceipt:
    """
    Immutable record of an accepted transfer.
    """
    transfer_id: str
    file_name: str
    file_sha256: str
    received_at: float
    sender_node_id: str
    classification_level: str
    merkle_root: str
    windows_received: int
    packets_received: int
    packets_dropped: int


def _ensure_dir(path: str, permissions: int) -> None:
    os.makedirs(path, exist_ok=True)
    os.chmod(path, permissions)


def _sanitize_filename(file_name: str) -> str:
    return os.path.basename(file_name)


class StorageWriter:
    """
    Persists verified files into secure storage.
    """

    def __init__(self, storage_dir: str = STORAGE_DIR, permissions: int = STORAGE_DIR_PERMISSIONS):
        self.storage_dir = storage_dir
        self.permissions = permissions
        _ensure_dir(self.storage_dir, self.permissions)

    @staticmethod
    def compute_sha256(file_bytes: bytes) -> str:
        return hashlib.sha256(file_bytes).hexdigest()

    def _build_destination(self, manifest: TransferManifest) -> str:
        safe_name = _sanitize_filename(manifest.file_name)
        return os.path.join(self.storage_dir, f"{manifest.transfer_id}_{safe_name}")

    def store_file(
        self,
        file_bytes: bytes,
        manifest: TransferManifest,
        packets_received: int = 0,
        packets_dropped: int = 0,
    ) -> str:
        """
        Store file bytes in secure storage and write receipt.

        Returns:
            Path to stored file.
        """
        destination = self._build_destination(manifest)
        temp_path = destination + ".tmp"

        with open(temp_path, "wb") as handle:
            handle.write(file_bytes)

        os.replace(temp_path, destination)
        os.chmod(destination, self.permissions)

        receipt = StorageReceipt(
            transfer_id=manifest.transfer_id,
            file_name=manifest.file_name,
            file_sha256=self.compute_sha256(file_bytes),
            received_at=time.time(),
            sender_node_id=manifest.sender_node_id,
            classification_level=manifest.classification_level,
            merkle_root=manifest.merkle_root,
            windows_received=manifest.total_windows,
            packets_received=packets_received,
            packets_dropped=packets_dropped,
        )

        self._write_receipt(destination, receipt)
        logger.info("Stored file %s with receipt", destination)
        return destination

    def _write_receipt(self, file_path: str, receipt: StorageReceipt) -> None:
        receipt_path = file_path + ".receipt.json"
        with open(receipt_path, "w", encoding="utf-8") as handle:
            json.dump(receipt.__dict__, handle, indent=2)
        os.chmod(receipt_path, self.permissions)

    def load_receipt(self, file_path: str) -> Optional[dict]:
        receipt_path = file_path + ".receipt.json"
        if not os.path.exists(receipt_path):
            return None
        with open(receipt_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
