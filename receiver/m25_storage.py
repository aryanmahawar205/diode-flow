"""Moves verified file from quarantine to secure storage."""
from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path
from common.models import TransferManifest

logger = logging.getLogger(__name__)


def store(quarantine_path: Path, storage_dir: str,
          manifest: TransferManifest, stats: dict) -> bool:
    storage = Path(storage_dir)
    storage.mkdir(parents=True, exist_ok=True)

    dest = storage / manifest.file_name
    quarantine_path.rename(dest)
    os.chmod(dest, 0o440)

    receipt = {
        "transfer_id"        : manifest.transfer_id,
        "file_name"          : manifest.file_name,
        "original_sha256"    : manifest.original_sha256,
        "received_at"        : time.time(),
        "sender_node_id"     : manifest.sender_node_id,
        "classification"     : manifest.classification_level,
        "compression"        : manifest.compression_algorithm,
        "original_size_bytes": manifest.original_size,
        **stats,
    }
    receipt_path = storage / f"{manifest.transfer_id[:8]}_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2))

    logger.info(f"ACCEPTED: {dest} | Receipt: {receipt_path}")
    return True
