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
    for wid in range(total_windows):
        if wid < total_windows - 1:
            win_chunks = window_size // chunk_size
        else:
            # Last window may be smaller
            prev_total = (total_windows - 1) * (window_size // chunk_size)
            win_chunks = total_chunks - prev_total
        window_chunk_counts.append(win_chunks)

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
        ed25519_signature     = b"phase3_placeholder",
        window_chunk_counts   = window_chunk_counts,
    )

    logger.info(f"Manifest: transfer={manifest.transfer_id[:8]}, "
                f"file={manifest.file_name}, "
                f"size={manifest.file_size/1024**2:.1f}MB, "
                f"windows={total_windows}, chunks={total_chunks}")
    return manifest
