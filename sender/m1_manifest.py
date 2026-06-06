"""
Generates the TransferManifest that is sent before all data packets.
Receiver uses manifest to pre-configure decode sessions and validate hard limits.
"""
from __future__ import annotations
import logging
import mimetypes
import os
import time
import uuid
from common.models import TransferManifest, CompressionResult
from common.config import DEFAULT_CHUNK_SIZE, PROTOCOL_VERSION
from sender.m0_compress import sha256_streaming
from sender.m4_merkle import global_root_streaming
from common.crypto import sign_manifest

logger = logging.getLogger(__name__)


def generate_manifest(
    original_file_name   : str,
    compressed_path     : str,
    compress_result     : CompressionResult,
    total_windows       : int,
    window_size         : int,
    profile,
    classification      : str = "standard",
    sender_node_id      : str = "sender-001",
    chunk_size          : int = DEFAULT_CHUNK_SIZE,
) -> TransferManifest:

    compressed_size = os.path.getsize(compressed_path)
    total_chunks    = (compressed_size + chunk_size - 1) // chunk_size
    merkle_root     = global_root_streaming(compressed_path, chunk_size)
    mime, _         = mimetypes.guess_type(compress_result.compressed_path)

    # FIX H: Compute chunk count for each window
    window_chunk_counts = []

    remaining_bytes = compressed_size

    for wid in range(total_windows):
        current_window_bytes = min(window_size, remaining_bytes)

        win_chunks = (
            current_window_bytes + chunk_size - 1
        ) // chunk_size

        window_chunk_counts.append(win_chunks)

        remaining_bytes -= current_window_bytes

    manifest = TransferManifest(
        transfer_id           = str(uuid.uuid4()),
        sender_node_id        = sender_node_id,
        protocol_version      = PROTOCOL_VERSION,
        file_name             = original_file_name,
        file_size             = compressed_size,
        file_sha256           = compress_result.compressed_sha256,
        original_size         = compress_result.original_size,
        original_sha256       = compress_result.original_sha256,
        compression_algorithm = compress_result.algorithm,
        chunk_size            = chunk_size,
        total_chunks          = total_chunks,
        total_windows         = total_windows,
        window_size_bytes     = window_size,
        rs_n                  = profile.rs_n,
        rs_k                  = profile.rs_k,
        num_passes            = profile.num_passes,
        overhead_ratio        = profile.overhead_ratio,
        interleave_depth      = profile.interleave_depth,
        merkle_root           = merkle_root,
        mime_type             = mime or "application/octet-stream",
        creation_timestamp    = time.time(),
        classification_level  = classification,
        expiration_policy     = 3600,
        ed25519_signature     = b"",
        window_chunk_counts   = window_chunk_counts,
    )

    manifest_dict = {
        "transfer_id": manifest.transfer_id,
        "sender_node_id": manifest.sender_node_id,
        "protocol_version": manifest.protocol_version,
        "file_name": manifest.file_name,
        "file_size": manifest.file_size,
        "file_sha256": manifest.file_sha256,
        "original_size": manifest.original_size,
        "original_sha256": manifest.original_sha256,
        "compression_algorithm": manifest.compression_algorithm,
        "chunk_size": manifest.chunk_size,
        "total_chunks": manifest.total_chunks,
        "total_windows": manifest.total_windows,
        "window_size_bytes": manifest.window_size_bytes,
        "rs_n": manifest.rs_n,
        "rs_k": manifest.rs_k,
        "num_passes": manifest.num_passes,
        "overhead_ratio": manifest.overhead_ratio,
        "interleave_depth": manifest.interleave_depth,
        "merkle_root": manifest.merkle_root,
        "mime_type": manifest.mime_type,
        "creation_timestamp": manifest.creation_timestamp,
        "classification_level": manifest.classification_level,
        "expiration_policy": manifest.expiration_policy,
        "window_chunk_counts": manifest.window_chunk_counts,
    }

    manifest.ed25519_signature = sign_manifest(manifest_dict)

    logger.info(f"Manifest: transfer={manifest.transfer_id[:8]}, "
                f"file={manifest.file_name}, "
                f"size={manifest.file_size/1024**2:.1f}MB, "
                f"windows={total_windows}, chunks={total_chunks}")
    return manifest
