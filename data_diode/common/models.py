"""
Shared dataclasses and types used across sender and receiver modules.

This module defines all data structures transferred between pipeline components.
Every module imports these definitions to ensure type consistency.

Design principle:
- One source of truth for all data structures
- Dataclasses enforce immutability (frozen=True where applicable)
- No circular imports (this module is completely standalone)
- Type hints on every field for IDE support and static analysis
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ==============================================================================
# TRANSFER MANIFEST
# ==============================================================================


@dataclass
class TransferManifest:
    """
    Complete description of a file transfer.

    Transmitted before data packets. Receiver uses this to:
    - Validate protocol version compatibility
    - Pre-allocate decoder resources
    - Enforce hard limits (prevent DoS via extreme K, RS parameters)
    - Configure per-window decode sessions
    """
    transfer_id: str              # UUID4, unique per transfer
    sender_node_id: str           # configurable sender identifier
    protocol_version: str         # e.g. "1.0.0" — schema versioning
    file_name: str                # original filename
    file_size: int                # bytes
    file_sha256: str              # hex SHA-256 of original file
    chunk_size: int               # bytes per chunk (fixed, except last padded)
    total_chunks: int             # K — original chunks before RS
    rs_n: int                     # Reed-Solomon n parameter (data + parity)
    rs_k: int                     # Reed-Solomon k parameter (parity only)
    num_passes: int               # LT encoding passes
    overhead_ratio: float         # per-pass overhead fraction
    interleave_depth: int         # packet interleave stride
    window_size_bytes: int        # bytes per window
    total_windows: int            # number of windows
    merkle_root: str              # hex Merkle root of all chunk hashes
    mime_type: str                # file MIME type
    creation_timestamp: float     # Unix epoch, sender wall clock
    classification_level: str     # "standard" | "critical" | "classified"
    expiration_policy: int        # seconds after which transfer is invalid
    ed25519_signature: bytes      # Ed25519 sig over all above fields (optional for Phase 1)


# ==============================================================================
# WINDOW MANIFEST (per-window metadata)
# ==============================================================================


@dataclass
class WindowManifest:
    """
    Per-window metadata transmitted before that window's data packets.

    Allows receiver to:
    - Know exactly how many chunks in this window
    - Allocate Merkle verifier for window subtree
    - Validate chunk count against hard limits
    """
    transfer_id: str              # Links to parent TransferManifest
    window_id: int                # 0-indexed window number
    window_offset: int            # byte offset in original file
    window_size: int              # actual bytes in this window (may be < window_size_bytes for last window)
    chunk_count: int              # K_window (chunks before RS parity)
    chunk_count_with_rs: int      # K_window + parity (what fountain encoder receives)
    padding_length: int           # bytes of zero-padding in last chunk (receiver removes these)
    window_merkle_root: str       # hex Merkle root for this window's chunks only


# ==============================================================================
# ENCODED PACKET METADATA
# ==============================================================================


@dataclass
class EncodedPacketMetadata:
    """
    Metadata attached to each encoded packet (separate from payload).

    Allows receiver to:
    - Route packet to correct transfer + window + pass
    - Reject packets with invalid fountain degree
    - Verify packet authenticity (BLAKE3-MAC)
    """
    transfer_id: str              # Links to transfer
    window_id: int                # Which window
    pass_id: int                  # Which encoding pass (0, 1, 2, ...)
    packet_id: int                # Sequence within pass (for ordering)
    fountain_degree: int          # Number of chunks XORed into this packet
    fountain_seed: int            # PRNG seed (decoder reconstructs degree selection)
    crc32c: int                   # CRC32C of payload (fast integrity check)
    blake3_mac: bytes             # BLAKE3-MAC of metadata + payload (cryptographic integrity)


# ==============================================================================
# CHUNK REPRESENTATION
# ==============================================================================


@dataclass
class Chunk:
    """
    A decoded chunk with verification data.

    On receiver side, chunks are verified at multiple levels:
    - Per-packet CRC32C (metadata.crc32c)
    - Per-chunk Merkle hash
    - Per-window Merkle subtree
    - Per-file Merkle root + SHA-256
    """
    chunk_id: int                 # global 0-indexed chunk number
    data: bytes                   # chunk payload (fixed size)
    window_id: int                # which window this belongs to
    chunk_sha256: str             # hex SHA-256 of this chunk (from Merkle tree)
    is_verified: bool = False     # set to True after Merkle verification


# ==============================================================================
# MERKLE TREE STRUCTURES
# ==============================================================================


@dataclass
class MerkleProof:
    """
    Proof that a leaf (chunk) belongs to a Merkle tree.

    Proof path is list of sibling hashes walking from leaf to root.
    Receiver verifies: compute_merkle_path(chunk_hash, proof) == expected_root
    """
    chunk_id: int                 # which chunk this proves
    leaf_hash: str                # hex SHA-256 of the chunk
    proof_path: list[str]         # list of hex hashes (siblings) for path to root
    root_hash: str                # expected Merkle root


@dataclass
class MerkleTree:
    """
    Binary Merkle tree for a set of chunks.

    Provides O(log N) proof generation and verification.
    """
    chunks: list[bytes]           # source chunks (leaves)
    leaves: list[str] = field(default_factory=list)  # hex SHA-256 hashes of chunks
    root: str = ""                # hex Merkle root
    tree: list[list[str]] = field(default_factory=list)  # full tree (bottom-up levels)

    def get_proof(self, chunk_id: int) -> MerkleProof:
        """Generate proof that chunk_id belongs to this tree."""
        # This will be implemented in sender/m3_merkle.py
        pass


# ==============================================================================
# TRANSFER PROFILE (robustness configuration)
# ==============================================================================


@dataclass
class TransferProfile:
    """
    Complete robustness configuration for a file transfer.

    Selected by m5_profile.py based on file size and criticality.
    Propagates to all downstream modules.
    """
    num_passes: int               # LT encoding passes (more = better burst loss protection)
    overhead_ratio: float         # per-pass overhead (e.g., 0.5 = 50% extra packets)
    rs_n: int                     # Reed-Solomon total (data + parity)
    rs_k: int                     # Reed-Solomon parity count
    interleave_depth: int         # packet reordering window size
    header_redundancy: int        # how many times to send manifest
    window_size_bytes: int        # max bytes per window (RAM budget constraint)


# ==============================================================================
# RECEIVER STATE (for window-level decode sessions)
# ==============================================================================


@dataclass
class WindowDecodeSession:
    """
    Per-window decode state on receiver side.

    Receiver maintains one session per window being decoded.
    Sessions are independent: one window failing doesn't block others.
    """
    transfer_id: str              # parent transfer
    window_id: int                # which window
    window_manifest: Optional[WindowManifest] = None
    chunks: dict[int, Optional[bytes]] = field(default_factory=dict)  # chunk_id -> bytes | None
    decoded: set[int] = field(default_factory=set)  # chunk_ids successfully decoded
    verified: set[int] = field(default_factory=set)  # chunk_ids verified by Merkle
    is_complete: bool = False
    error: Optional[str] = None
    data: Optional[bytes] = None # Fully reassembled window data


@dataclass
class TransferDecodeSession:
    """
    Global state for a complete transfer decode.

    Coordinates window sessions and file-level reassembly.
    """
    transfer_id: str
    manifest: Optional[TransferManifest] = None
    windows: dict[int, WindowDecodeSession] = field(default_factory=dict)
    received_packets: int = 0
    valid_packets: int = 0
    decoded_bytes: int = 0
    is_complete: bool = False
    error: Optional[str] = None


# ==============================================================================
# LOSS SIMULATION (for testing)
# ==============================================================================


@dataclass
class LossScenario:
    """
    Configurable packet loss scenario for testing robustness.

    Used by tests/utils/loss_simulator.py to inject failures.
    """
    name: str                     # e.g., "10% random loss"
    random_loss_rate: float = 0.0  # drop each packet with this probability
    burst_loss_start_frac: float = 0.0  # where burst starts (0.0 - 1.0)
    burst_loss_length: int = 0     # how many consecutive packets to drop
    corruption_rate: float = 0.0   # flip bits in this fraction of packets
    duplicate_rate: float = 0.0    # duplicate this fraction of packets
    reorder_window: int = 0        # sliding window size for random reordering
