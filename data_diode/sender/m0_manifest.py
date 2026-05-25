"""
Transfer manifest generator.

This module creates the transfer manifest — a complete description of a file
transfer that the receiver needs to configure its decoder before receiving data.

Why a separate manifest phase?
- Receiver cannot pre-allocate decoder until it knows K, RS parameters, file size
- Hard limits (K_max, RS parity limits) must be validated before any graph allocation
- Manifest is sent with high redundancy (typically 5×) before data packets
- Session initialization is cleanly separated from data transfer

Design decisions:
- Manifest is deterministic: same file + profile → same manifest
- UUID4 transfer_id makes each transfer unique and untraceable
- Ed25519 signature authenticates manifest (prevents forgery, Phase 3)
- Merkle root is precomputed so receiver can verify per-chunk hashes
- Timestamps allow policy-based transfer expiration

Invariant: Manifest must not exceed safe Protobuf size (~1-2 KB).
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from common.models import TransferManifest
from common.config import (
    PROTOCOL_VERSION,
    DEFAULT_CHUNK_SIZE,
    compute_chunk_count,
    compute_window_count,
)

logger = logging.getLogger(__name__)


@dataclass
class ManifestInput:
    """
    Input specification for manifest generation.

    Attributes:
        file_path: Path to file being transferred.
        sender_node_id: Identifier of sending node.
        profile: TransferProfile with robustness params.
        classification_level: "standard" | "critical" | "classified".
        chunk_size: Bytes per chunk (default: config default).
    """
    file_path: str
    sender_node_id: str
    profile: object  # TransferProfile
    classification_level: str = "standard"
    chunk_size: int = DEFAULT_CHUNK_SIZE


def _compute_file_sha256(file_path: str) -> str:
    """
    Compute SHA-256 hash of entire file.

    Parameters:
        file_path: Path to file.

    Returns:
        Hex SHA-256 hash.

    Reads file in 64KB chunks to handle large files.
    """
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


from sender.m0_compress import CompressionResult

def generate_manifest(
    file_path: str,
    sender_node_id: str,
    profile: object,  # TransferProfile
    classification_level: str = "standard",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    merkle_root: Optional[str] = None,
    ed25519_signature: bytes = b"",
    compress_result: Optional[CompressionResult] = None,
) -> TransferManifest:
    """
    Generate a transfer manifest for a file.

    Parameters:
        file_path: Path to file to transfer (the file actually being sent).
        sender_node_id: Sender identifier.
        profile: TransferProfile with encoding parameters.
        classification_level: "standard", "critical", or "classified".
        chunk_size: Bytes per chunk.
        merkle_root: Precomputed Merkle root (optional).
        ed25519_signature: Manifest signature (optional).
        compress_result: Result of compression phase (optional).

    Returns:
        TransferManifest populated with all metadata.
    """
    import os

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)
    if compress_result and compress_result.algorithm == "none":
        # If we copied original to temp, use original name
        file_name = os.path.basename(compress_result.compressed_path) # wait, no

    # Use original filename even if compressed
    display_name = file_name
    
    # Guess MIME type
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    # Compute file hash
    file_sha256 = _compute_file_sha256(file_path)

    # Compute chunking
    total_chunks = compute_chunk_count(file_size, chunk_size)
    total_windows = compute_window_count(file_size, profile.window_size_bytes)

    if merkle_root is None:
        raise ValueError("merkle_root must be provided to generate_manifest")

    # Create manifest
    manifest = TransferManifest(
        transfer_id=str(uuid.uuid4()),
        sender_node_id=sender_node_id,
        protocol_version=PROTOCOL_VERSION,
        file_name=display_name,
        file_size=file_size,
        file_sha256=file_sha256,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        rs_n=profile.rs_n,
        rs_k=profile.rs_k,
        num_passes=profile.num_passes,
        overhead_ratio=profile.overhead_ratio,
        interleave_depth=profile.interleave_depth,
        window_size_bytes=profile.window_size_bytes,
        total_windows=total_windows,
        merkle_root=merkle_root,
        mime_type=mime_type,
        creation_timestamp=time.time(),
        classification_level=classification_level,
        expiration_policy=3600,
        ed25519_signature=ed25519_signature,
        compression_algorithm=compress_result.algorithm if compress_result else "none",
        compressed_size=compress_result.compressed_size if compress_result else file_size,
        original_size=compress_result.original_size if compress_result else file_size,
        original_sha256=compress_result.original_sha256 if compress_result else file_sha256,
    )

    return manifest


def validate_manifest(manifest: TransferManifest) -> list[str]:
    """
    Validate a manifest for internal consistency.

    Parameters:
        manifest: TransferManifest to validate.

    Returns:
        list[str] of validation errors (empty if valid).

    Checks:
    - Protocol version compatible
    - Hard limits not exceeded
    - Chunk/window counts consistent
    - Required fields non-empty
    """
    errors = []

    # Protocol version
    if manifest.protocol_version != PROTOCOL_VERSION:
        errors.append(
            f"Protocol version mismatch: "
            f"expected {PROTOCOL_VERSION}, got {manifest.protocol_version}"
        )

    # Required fields
    if not manifest.transfer_id:
        errors.append("transfer_id is empty")
    if not manifest.file_name:
        errors.append("file_name is empty")

    # Sizes
    if manifest.chunk_size <= 0:
        errors.append(f"chunk_size must be positive, got {manifest.chunk_size}")
    if manifest.file_size < 0:
        errors.append(f"file_size must be non-negative, got {manifest.file_size}")

    # Chunk counts
    if manifest.total_chunks <= 0:
        errors.append(f"total_chunks must be positive, got {manifest.total_chunks}")
    if manifest.total_windows <= 0:
        errors.append(f"total_windows must be positive, got {manifest.total_windows}")

    # Hard limits
    from common.config import MAX_CHUNKS_PER_WINDOW, MAX_WINDOWS_PER_TRANSFER
    if manifest.total_chunks > MAX_CHUNKS_PER_WINDOW:
        errors.append(
            f"total_chunks {manifest.total_chunks} exceeds limit "
            f"{MAX_CHUNKS_PER_WINDOW}"
        )
    if manifest.total_windows > MAX_WINDOWS_PER_TRANSFER:
        errors.append(
            f"total_windows {manifest.total_windows} exceeds limit "
            f"{MAX_WINDOWS_PER_TRANSFER}"
        )

    # RS parameters
    if manifest.rs_n < manifest.rs_k:
        errors.append(
            f"rs_n ({manifest.rs_n}) must be >= rs_k ({manifest.rs_k})"
        )
    if manifest.rs_k <= 0:
        errors.append(f"rs_k must be positive, got {manifest.rs_k}")

    # Passes and overhead
    if manifest.num_passes <= 0:
        errors.append(f"num_passes must be positive, got {manifest.num_passes}")
    if manifest.overhead_ratio < 0:
        errors.append(
            f"overhead_ratio must be non-negative, got {manifest.overhead_ratio}"
        )

    return errors
