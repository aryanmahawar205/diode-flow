"""
Shared data structures for the entire data diode system.
No imports from sender/ or receiver/ — zero circular import risk.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class TransferProfile:
    """Robustness configuration selected by m6_profile.py."""
    num_passes        : int    # fountain encoding passes (1 or 2)
    overhead_ratio    : float  # extra packets fraction e.g. 0.20 = 20%
    rs_n              : int    # Reed-Solomon total block size
    rs_k              : int    # Reed-Solomon parity count (= n - data_count)
    interleave_depth  : int    # stride for packet reordering
    header_redundancy : int    # how many times to send manifest
    window_size_bytes : int    # max bytes per processing window


@dataclass
class TransferManifest:
    """
    Complete transfer description. Sent before any data packets.
    file_size and file_sha256 refer to COMPRESSED bytes (in transit).
    original_size and original_sha256 refer to the file before compression.
    FIX H: Store per-window chunk counts to avoid fallback miscalculation.
    """
    transfer_id           : str
    sender_node_id        : str
    protocol_version      : str
    file_name             : str
    file_size             : int    # compressed size
    file_sha256           : str    # sha256 of compressed bytes
    original_size         : int    # size before compression
    original_sha256       : str    # sha256 of original file
    compression_algorithm : str    # "lz4" or "none"
    chunk_size            : int
    total_chunks          : int    # K across entire file
    total_windows         : int
    window_size_bytes     : int
    rs_n                  : int
    rs_k                  : int
    num_passes            : int
    overhead_ratio        : float
    interleave_depth      : int
    merkle_root           : str    # global Merkle root
    mime_type             : str
    creation_timestamp    : float
    classification_level  : str    # "standard" | "critical" | "classified"
    expiration_policy     : int    # seconds
    ed25519_signature     : bytes  # signs all above fields
    window_chunk_counts   : list[int] = None  # FIX H: K for each window [chunks for wid 0, 1, ...]


@dataclass
class WindowManifest:
    """Per-window metadata. Tells receiver how to decode this window."""
    transfer_id          : str
    window_id            : int
    window_offset        : int    # byte offset in compressed file
    window_size          : int    # actual bytes in this window
    chunk_count          : int    # K for this window (before RS)
    chunk_count_with_rs  : int    # K + parity chunks (K')
    padding_length       : int    # zero-padding bytes in last chunk
    window_merkle_root   : str    # Merkle root for this window only


@dataclass
class EncodedPacket:
    """FIX B — explicitly store chunk_ids."""
    packet_id          : int
    pass_id            : int
    seed               : int
    degree             : int
    chunk_ids          : list[int]   # ADD THIS — which chunks were XOR'd
    data               : bytes
    source_chunk_count : int         # K' = data chunks + RS parity chunks


@dataclass
class DecodeResult:
    """Output of fountain decoder."""
    chunks          : list[bytes | None]  # None = not recovered
    success         : bool
    recovered_count : int
    missing_ids     : list[int]
    packets_used    : int


@dataclass
class MerkleProofStep:
    """One step in a Merkle proof path from leaf to root."""
    sibling_hash : str
    is_left      : bool   # True = sibling is the LEFT child


@dataclass
class CompressionResult:
    compressed_path   : str
    original_size     : int
    compressed_size   : int
    compression_ratio : float
    algorithm         : str    # "lz4" or "none"
    original_sha256   : str
    compressed_sha256 : str


@dataclass
class TransferProgress:
    """Progress tracking for large file transfers."""
    transfer_id       : str
    file_name         : str
    total_windows     : int
    completed_windows : int   = 0
    total_packets_rx  : int   = 0
    start_time        : float = field(default_factory=time.time)

    @property
    def pct(self) -> float:
        return (self.completed_windows / self.total_windows * 100
                if self.total_windows else 0.0)

    @property
    def eta_str(self) -> str:
        if self.completed_windows == 0:
            return "unknown"
        rate = self.completed_windows / max(time.time() - self.start_time, 0.001)
        secs = (self.total_windows - self.completed_windows) / rate
        return f"{secs/60:.1f}min" if secs < 3600 else f"{secs/3600:.1f}hr"

    def log(self, logger) -> None:
        logger.info(
            f"[{self.transfer_id[:8]}] Window {self.completed_windows}/"
            f"{self.total_windows} ({self.pct:.1f}%) | ETA: {self.eta_str} | "
            f"Packets received: {self.total_packets_rx:,}"
        )
