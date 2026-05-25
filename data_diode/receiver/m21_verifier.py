"""
Final verification of transferred file.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from sender.m3_merkle import _build_merkle_root_from_hashes

logger = logging.getLogger(__name__)


class FileVerifier:
    """
    Verifies integrity of reassembled files.
    """

    @staticmethod
    def verify_sha256_streaming(file_path: str, expected_hash: str) -> bool:
        """
        Compute SHA256 of file on disk in 64KB blocks.
        """
        sha256 = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                while True:
                    block = f.read(65536)
                    if not block:
                        break
                    sha256.update(block)
            
            actual = sha256.hexdigest()
            if hmac.compare_digest(actual, expected_hash):
                logger.info(f"SHA256 match: {actual[:16]}...")
                return True
            else:
                logger.error(f"SHA256 mismatch: {actual} != {expected_hash}")
                return False
        except Exception as e:
            logger.error(f"SHA256 verification error: {e}")
            return False

    @staticmethod
    def verify_merkle_root(window_merkle_roots: list[str], expected_root: str) -> bool:
        """
        Verify global Merkle root by combining window roots.
        """
        if not window_merkle_roots:
            return False
            
        try:
            computed_root = _build_merkle_root_from_hashes(window_merkle_roots)
            if hmac.compare_digest(computed_root, expected_root):
                logger.info(f"Global Merkle root match: {computed_root[:16]}...")
                return True
            else:
                logger.error(f"Merkle root mismatch: {computed_root} != {expected_root}")
                return False
        except Exception as e:
            logger.error(f"Merkle verification error: {e}")
            return False
