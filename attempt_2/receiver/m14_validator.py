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

logger = logging.getLogger(__name__)


def validate_manifest(m: TransferManifest) -> tuple[bool, str]:
    """
    Returns (True, "") if manifest passes all checks.
    Returns (False, reason) if it fails.
    Called before allocating ANY decode resources.
    """
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

        # Transfer ID match
        if d["transfer_id"] != manifest.transfer_id:
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
