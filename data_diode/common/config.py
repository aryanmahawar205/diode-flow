"""
Global configuration constants and profile tables.

This module defines all tunable parameters and default values used across
the system. It's the single source of truth for:
- Protocol version and compatibility
- Hard limits (prevents DoS attacks)
- Default chunk/window sizes
- Profile tables (robustness vs file size/criticality)
- UDP settings
- Timeout values

Modifying this file propagates to all modules automatically.
"""

from __future__ import annotations

from .models import TransferProfile

# ==============================================================================
# PROTOCOL VERSION (schema versioning for forward compatibility)
# ==============================================================================

PROTOCOL_VERSION = "1.0.0"

# ==============================================================================
# CHUNK SIZING (based on typical UDP MTU)
# ==============================================================================

# MTU = 1500 bytes (standard Ethernet)
# - IP header: 20 bytes
# - UDP header: 8 bytes
# - Protobuf overhead: ~50 bytes
# - Metadata: ~100 bytes
# = 1322 bytes theoretical max
# Use 1200 for safety margin
DEFAULT_CHUNK_SIZE = 1200

# Minimum chunk size (avoid tiny packets)
MIN_CHUNK_SIZE = 64

# Maximum chunk size (avoid too few chunks for good PRNG distribution)
MAX_CHUNK_SIZE = 16384

# ==============================================================================
# WINDOW SIZING (bounded memory for large files)
# ==============================================================================

# RAM budget for Tanner graph:
# - At K=60000 chunks, roughly 100-200 MB for graph structure
# - Leave headroom for encoding/decoding buffers
# - Adaptive: can be overridden by m5_profile.py based on system RAM

DEFAULT_WINDOW_SIZE_BYTES = 64 * 1024 * 1024  # 64 MB default
MIN_WINDOW_SIZE_BYTES = 16 * 1024 * 1024      # 16 MB minimum
MAX_WINDOW_SIZE_BYTES = 512 * 1024 * 1024     # 512 MB maximum (safety limit)

# ==============================================================================
# HARD LIMITS (prevent DoS: decoder should reject manifest with K > limit)
# ==============================================================================

# Maximum chunks per window (bounded Tanner graph)
# At 1200-byte chunks: 64MB / 1200 ≈ 55k chunks
# Limit to 120k to stay safely in memory
MAX_CHUNKS_PER_WINDOW = 120000

# Maximum RS parity (prevent massive RS encoding)
MAX_RS_PARITY = 128

# Maximum passes (prevent combinatorial explosion)
MAX_PASSES = 2

# Maximum total windows in a transfer
MAX_WINDOWS_PER_TRANSFER = 10000

# Maximum file size (practical limit)
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024 * 1024  # 100 GB

# ==============================================================================
# TRANSFER PROFILES (robustness configuration by file size + criticality)
# ==============================================================================

# Size categories (by file size in bytes)
FILE_SIZES = {
    "small": (0, 64 * 1024 * 1024),              # < 64 MB (updated to match new windowing logic)
    "medium": (64 * 1024 * 1024, 1024**3),       # 64 MB - 1 GB
    "large": (1024**3, float('inf')),            # > 1 GB
}

# Criticality levels
CRITICALITY_LEVELS = ["standard", "critical", "classified"]

# Profile table: (size_category, criticality) -> TransferProfile
PROFILES: dict[tuple[str, str], TransferProfile] = {
    # Small files (< 64 MB) — redundancy priority
    ("small", "standard"):    TransferProfile(
        num_passes=1, overhead_ratio=0.5, rs_n=20, rs_k=14,
        interleave_depth=2, header_redundancy=3,
        window_size_bytes=16 * 1024 * 1024,
    ),

    ("small", "critical"):    TransferProfile(
        num_passes=2, overhead_ratio=0.4, rs_n=24, rs_k=12,
        interleave_depth=3, header_redundancy=5,
        window_size_bytes=16 * 1024 * 1024,
    ),

    # Medium files (64 MB – 1 GB) — balanced
    ("medium", "standard"):   TransferProfile(
        num_passes=1, overhead_ratio=0.30, rs_n=32, rs_k=32,
        interleave_depth=3, header_redundancy=3,
        window_size_bytes=64 * 1024 * 1024,
    ),
    ("medium", "critical"):   TransferProfile(
        num_passes=2, overhead_ratio=0.35, rs_n=32, rs_k=32,
        interleave_depth=4, header_redundancy=5,
        window_size_bytes=64 * 1024 * 1024,
    ),

    # Large files (> 1 GB) — performance priority, large windows
    ("large", "standard"):    TransferProfile(
        num_passes=1, overhead_ratio=0.25, rs_n=64, rs_k=64,
        interleave_depth=4, header_redundancy=3,
        window_size_bytes=128 * 1024 * 1024,
    ),
    ("large", "critical"):    TransferProfile(
        num_passes=2, overhead_ratio=0.30, rs_n=64, rs_k=64,
        interleave_depth=6, header_redundancy=5,
        window_size_bytes=128 * 1024 * 1024,
    ),

    # Catch-all profiles
    ("any", "classified"):    TransferProfile(
        num_passes=2, overhead_ratio=0.25, rs_n=32, rs_k=24,
        interleave_depth=5, header_redundancy=5,
        window_size_bytes=64 * 1024 * 1024,
    ),
}

# ==============================================================================
# UDP TRANSMISSION SETTINGS
# ==============================================================================

# Default UDP port (configurable at runtime)
DEFAULT_UDP_PORT = 20000

# Loopback address for simulation
LOOPBACK_ADDRESS = "127.0.0.1"

# Transmitter rate limit (packets per second)
# 0 = unlimited, > 0 = packets/sec
DEFAULT_TRANSMISSION_RATE_LIMIT = 0

# Receiver buffer size (ring buffer capacity)
RECEIVER_RING_BUFFER_SIZE = 100000  # packets

# ==============================================================================
# TIMEOUT VALUES (seconds)
# ==============================================================================

# How long to wait for complete manifest (Phase 0)
MANIFEST_TIMEOUT = 30.0

# How long to wait for complete window (Phase 1/2/...)
WINDOW_TIMEOUT = 60.0

# How long to hold packets before aging out (packet deduplication)
PACKET_DEDUP_TIMEOUT = 120.0

# How long to keep transfer state before cleanup
TRANSFER_CLEANUP_TIMEOUT = 3600.0

# ==============================================================================
# QUARANTINE & STORAGE
# ==============================================================================

# Directory for incomplete/quarantined transfers
QUARANTINE_DIR = "demo_output/quarantine"

# Directory for verified transfers
STORAGE_DIR = "demo_output/storage"

# Permissions for storage directory (octal)
STORAGE_DIR_PERMISSIONS = 0o700

# ==============================================================================
# LOGGING
# ==============================================================================

# Default log level
DEFAULT_LOG_LEVEL = "INFO"

# Log format
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def get_profile(file_size: int, criticality: str) -> TransferProfile:
    """
    Get the transfer profile for a file.

    Parameters:
        file_size: Bytes.
        criticality: "standard", "critical", or "classified".

    Returns:
        TransferProfile instance.

    Raises:
        ValueError: if criticality not recognized.
    """
    if criticality not in CRITICALITY_LEVELS:
        raise ValueError(
            f"criticality must be one of {CRITICALITY_LEVELS}, got '{criticality}'"
        )

    # Find size category
    size_cat = None
    for cat, (min_size, max_size) in FILE_SIZES.items():
        if min_size <= file_size < max_size:
            size_cat = cat
            break

    if size_cat is None:
        size_cat = "large"  # default to large for huge files

    key = (size_cat, criticality)
    if key not in PROFILES:
        # Fallback to catch-all
        key = ("any", criticality)
        if key not in PROFILES:
            raise ValueError(f"No profile for {criticality}")

    return PROFILES[key]


def compute_chunk_count(window_size: int, chunk_size: int) -> int:
    """
    Compute how many chunks fit in a window.

    Parameters:
        window_size: Bytes in window.
        chunk_size: Bytes per chunk.

    Returns:
        Number of chunks (K).
    """
    return (window_size + chunk_size - 1) // chunk_size  # ceiling division


def compute_window_count(file_size: int, window_size: int) -> int:
    """
    Compute how many windows a file requires.

    Parameters:
        file_size: Total bytes.
        window_size: Bytes per window.

    Returns:
        Number of windows.
    """
    return (file_size + window_size - 1) // window_size
