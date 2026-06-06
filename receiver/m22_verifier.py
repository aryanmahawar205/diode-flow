"""
Final end-to-end integrity verification.
Two independent checks: SHA-256 of assembled file + file size.
Both must pass. Uses streaming SHA-256 — safe for any file size.
"""
from __future__ import annotations
import hashlib
import hmac
import logging
from pathlib import Path
from common.models import TransferManifest

logger = logging.getLogger(__name__)


def verify_file(path: Path, manifest: TransferManifest) -> bool:
    """
    Verify assembled compressed file against manifest.
    Checks: file exists, size matches, SHA-256 matches.
    """
    if not path.exists():
        logger.error("Output file does not exist")
        return False

    actual_size = path.stat().st_size
    if actual_size != manifest.file_size:
        logger.error(f"Size mismatch: expected {manifest.file_size}, "
                     f"got {actual_size}")
        return False

    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            sha256.update(chunk)

    actual_hash = sha256.hexdigest()
    if not hmac.compare_digest(actual_hash, manifest.file_sha256):
        logger.error("SHA-256 mismatch on assembled file")
        return False

    logger.info(
    f"SHA-256 verified successfully "
    f"for {path.name}"
)
    return True
