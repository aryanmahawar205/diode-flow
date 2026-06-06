"""
Packet and manifest validation gate.
Every check must pass before a packet enters the decode pool.
Hard limits enforced here — before any Tanner graph memory is allocated.
Silent drops — no error ever sent back.
"""
from __future__ import annotations
import logging
import time
from common.config import (MAX_DEGREE, MAX_K_TOTAL, MAX_TRANSFER_SIZE,
                            MAX_PASSES, MAX_WINDOWS, MAX_RS_PARITY)
from common.models import TransferManifest
from common.crypto import verify_manifest

logger = logging.getLogger(__name__)


def validate_manifest(m: TransferManifest) -> tuple[bool, str]:
    """
    Returns (True, "") if manifest passes all checks.
    Returns (False, reason) if it fails.
    Called before allocating ANY decode resources.
    """
    
    manifest_dict = {
    "transfer_id": m.transfer_id,
    "sender_node_id": m.sender_node_id,
    "protocol_version": m.protocol_version,
    "file_name": m.file_name,
    "file_size": m.file_size,
    "file_sha256": m.file_sha256,
    "original_size": m.original_size,
    "original_sha256": m.original_sha256,
    "compression_algorithm": m.compression_algorithm,
    "chunk_size": m.chunk_size,
    "total_chunks": m.total_chunks,
    "total_windows": m.total_windows,
    "window_size_bytes": m.window_size_bytes,
    "rs_n": m.rs_n,
    "rs_k": m.rs_k,
    "num_passes": m.num_passes,
    "overhead_ratio": m.overhead_ratio,
    "interleave_depth": m.interleave_depth,
    "merkle_root": m.merkle_root,
    "mime_type": m.mime_type,
    "creation_timestamp": m.creation_timestamp,
    "classification_level": m.classification_level,
    "expiration_policy": m.expiration_policy,
    "window_chunk_counts": m.window_chunk_counts,
}

    if not verify_manifest(
        manifest_dict,
        m.ed25519_signature
    ):
        logger.warning("Manifest rejected: invalid Ed25519 signature")
        return False, "invalid manifest signature"
    
    logger.info(
    f"Manifest signature verified "
    f"(transfer={m.transfer_id[:8]})"
)

    checks = [
        (m.total_chunks   <= MAX_K_TOTAL,       f"total_chunks {m.total_chunks} > {MAX_K_TOTAL}"),
        (m.file_size      <= MAX_TRANSFER_SIZE,  f"file_size exceeds 100GB"),
        (m.num_passes     <= MAX_PASSES,         f"num_passes {m.num_passes} > {MAX_PASSES}"),
        (m.total_windows  <= MAX_WINDOWS,        f"total_windows {m.total_windows} > {MAX_WINDOWS}"),
        (m.rs_k           <= MAX_RS_PARITY,      f"rs_k {m.rs_k} > {MAX_RS_PARITY}"),
        (m.chunk_size     > 0,                   f"chunk_size must be positive"),
        (m.total_chunks   > 0,                   f"total_chunks must be positive"),
        (m.total_windows  > 0,                   f"total_windows must be positive"),
        (m.rs_n           > m.rs_k,              f"rs_n must be > rs_k"),
        (m.num_passes     >= 1,                  f"num_passes must be >= 1"),
        (m.overhead_ratio >= 0,                  f"overhead_ratio must be >= 0"),
        (m.classification_level in ("standard","critical","classified"),
                                                 f"invalid classification"),
    ]
    for ok, reason in checks:
        if not ok:
            logger.warning(f"Manifest rejected: {reason}")
            return False, reason
    return True, ""


def validate_packet_dict(d: dict, manifest: TransferManifest,
                          transfer_start: float) -> tuple[bool, str]:
    """Validate one decoded packet dict. Returns (ok, reason)."""
    try:
        # Required fields
        for field in ("transfer_id","window_id","pass_id","packet_id",
                      "seed","degree","chunk_ids","K_prime",
                      "padding_length","data_chunk_count","data"):
            if field not in d:
                return False, f"Missing field: {field}"

        # Degree cap (DoS guard)
        if not 1 <= d["degree"] <= MAX_DEGREE:
            return False, f"degree {d['degree']} out of range"

        # Transfer ID match (binary format uses truncated ID)
        if not manifest.transfer_id.startswith(d["transfer_id"]):
            return False, "transfer_id mismatch"

        # Window bounds
        if not 0 <= d["window_id"] < manifest.total_windows:
            return False, f"window_id {d['window_id']} out of range"

        # Pass bounds
        if not 0 <= d["pass_id"] < manifest.num_passes:
            return False, f"pass_id {d['pass_id']} out of range"

        # chunk_ids sanity
        if len(d["chunk_ids"]) != d["degree"]:
            return False, "chunk_ids length != degree"

        return True, ""
    except Exception as e:
        return False, f"validation error: {e}"
