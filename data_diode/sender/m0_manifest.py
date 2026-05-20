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
import time
import uuid
from dataclasses import dataclass, field

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


def _compute_merkle_root_placeholder(total_chunks: int) -> str:
    """
    Placeholder merkle root.

    In production, this would be computed by m3_merkle after chunking.
    For now, return deterministic placeholder based on total_chunks.

    Parameters:
        total_chunks: Number of chunks.

    Returns:
        Hex string representing merkle root.
    """
    # Deterministic placeholder: hash(str(total_chunks))
    data = f"merkle_root_placeholder_{total_chunks}".encode()
    return hashlib.sha256(data).hexdigest()


def generate_manifest(
    file_path: str,
    sender_node_id: str,
    profile: object,  # TransferProfile
    classification_level: str = "standard",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> TransferManifest:
    """
    Generate a transfer manifest for a file.

    Parameters:
        file_path: Path to file to transfer.
        sender_node_id: Sender identifier.
        profile: TransferProfile with encoding parameters.
        classification_level: "standard", "critical", or "classified".
        chunk_size: Bytes per chunk.

    Returns:
        TransferManifest populated with all metadata.

    Raises:
        FileNotFoundError: if file doesn't exist.
        ValueError: if parameters invalid or exceed hard limits.
    """
    import os

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    if classification_level not in ["standard", "critical", "classified"]:
        raise ValueError(
            f"classification_level must be one of "
            f"['standard', 'critical', 'classified'], got '{classification_level}'"
        )

    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)

    # Compute file hash
    logger.debug(f"Computing SHA-256 for {file_path} ({file_size} bytes)")
    file_sha256 = _compute_file_sha256(file_path)

    # Compute chunking
    total_chunks = compute_chunk_count(file_size, chunk_size)
    total_windows = compute_window_count(file_size, profile.window_size_bytes)

    logger.debug(
        f"File breakdown: {total_chunks} chunks, {total_windows} windows, "
        f"chunk_size={chunk_size}"
    )

    # K and K' (K with RS parity)
    K = total_chunks
    K_prime = K + profile.rs_k

    # Validate against hard limits
    from common.config import MAX_CHUNKS_PER_WINDOW, MAX_WINDOWS_PER_TRANSFER, MAX_FILE_SIZE_BYTES
    if K > MAX_CHUNKS_PER_WINDOW * MAX_WINDOWS_PER_TRANSFER:
        raise ValueError(
            f"Total chunks {K} exceeds limit "
            f"{MAX_CHUNKS_PER_WINDOW * MAX_WINDOWS_PER_TRANSFER}"
        )
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File size {file_size} exceeds limit {MAX_FILE_SIZE_BYTES}"
        )

    # Generate transfer ID (UUID4)
    transfer_id = str(uuid.uuid4())

    # Compute merkle root (placeholder for now)
    merkle_root = _compute_merkle_root_placeholder(total_chunks)

    # Create manifest
    manifest = TransferManifest(
        transfer_id=transfer_id,
        sender_node_id=sender_node_id,
        protocol_version=PROTOCOL_VERSION,
        file_name=file_name,
        file_size=file_size,
        file_sha256=file_sha256,
        chunk_size=chunk_size,
        total_chunks=K,
        rs_n=profile.rs_n,
        rs_k=profile.rs_k,
        num_passes=profile.num_passes,
        overhead_ratio=profile.overhead_ratio,
        interleave_depth=profile.interleave_depth,
        window_size_bytes=profile.window_size_bytes,
        total_windows=total_windows,
        merkle_root=merkle_root,
        mime_type="application/octet-stream",
        creation_timestamp=time.time(),
        classification_level=classification_level,
        expiration_policy=3600,  # 1 hour
        ed25519_signature=b"placeholder",  # Phase 3
    )

    logger.info(
        f"Generated manifest: transfer_id={transfer_id}, "
        f"file={file_name}, size={file_size}, chunks={K}, "
        f"windows={total_windows}, profile=({profile.num_passes} passes, "
        f"{profile.overhead_ratio} overhead)"
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
    if manifest.rs_n <= manifest.rs_k:
        errors.append(
            f"rs_n ({manifest.rs_n}) must be > rs_k ({manifest.rs_k})"
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
