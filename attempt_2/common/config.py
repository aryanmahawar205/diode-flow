"""
Global constants. Single source of truth.
Changing a value here propagates everywhere automatically.
"""
from __future__ import annotations
from common.models import TransferProfile

PROTOCOL_VERSION = "1.0.0"

# Chunk sizing: MTU(1500) - IP(20) - UDP(8) - metadata(~150) - protobuf(~50)
DEFAULT_CHUNK_SIZE = 1200

# Hard limits — enforced before any decoder memory is allocated
MAX_CHUNKS_PER_WINDOW  = 1_000_000
MAX_K_TOTAL            = 10_000_000
MAX_TRANSFER_SIZE      = 100 * 1024**3   # 100 GB
MAX_PASSES             = 2               # never 3
MAX_WINDOWS            = 50_000
MAX_DEGREE             = 10000           # fountain packet degree cap
MAX_RS_PARITY          = 255             # increased for better blocks

# Timeouts
MANIFEST_TIMEOUT_S = 30.0
WINDOW_TIMEOUT_S   = 300.0           # increased for large processing tasks
TRANSFER_TIMEOUT_S = 14400.0         # 4 hours

# Storage
QUARANTINE_DIR = "demo_output/quarantine"
STORAGE_DIR    = "demo_output/storage"
WINDOWS_TMP    = "demo_output/windows_tmp"

# UDP
DEFAULT_PORT        = 20000
DEFAULT_ADDRESS     = "127.0.0.1"
UDP_RECV_BUFFER     = 64 * 1024 * 1024  # 64MB OS recv buffer
UDP_SEND_BUFFER     = 16 * 1024 * 1024  # 16MB OS send buffer
MAX_UDP_PAYLOAD     = 65507             # max UDP datagram

# Transfer profiles
PROFILES: dict[tuple[str, str], TransferProfile] = {
    ("small",  "standard"):   TransferProfile(num_passes=1, overhead_ratio=0.40,
        rs_n=34, rs_k=2, interleave_depth=2, header_redundancy=3,
        window_size_bytes=16*1024*1024),
    ("small",  "critical"):   TransferProfile(num_passes=2, overhead_ratio=0.40,
        rs_n=36, rs_k=4, interleave_depth=3, header_redundancy=5,
        window_size_bytes=16*1024*1024),
    ("small",  "classified"): TransferProfile(num_passes=2, overhead_ratio=0.50,
        rs_n=40, rs_k=8, interleave_depth=4, header_redundancy=5,
        window_size_bytes=16*1024*1024),
    ("medium", "standard"):   TransferProfile(num_passes=1, overhead_ratio=0.08,
        rs_n=66, rs_k=2, interleave_depth=3, header_redundancy=2,
        window_size_bytes=1024*1024*1024),
    ("medium", "critical"):   TransferProfile(num_passes=2, overhead_ratio=0.30,
        rs_n=68, rs_k=4, interleave_depth=4, header_redundancy=5,
        window_size_bytes=64*1024*1024),
    ("medium", "classified"): TransferProfile(num_passes=2, overhead_ratio=0.35,
        rs_n=72, rs_k=8, interleave_depth=5, header_redundancy=5,
        window_size_bytes=64*1024*1024),
    ("large",  "standard"):   TransferProfile(num_passes=1, overhead_ratio=0.05,
        rs_n=130, rs_k=2, interleave_depth=4, header_redundancy=2,
        window_size_bytes=1024*1024*1024),
    ("large",  "critical"):   TransferProfile(num_passes=2, overhead_ratio=0.25,
        rs_n=132, rs_k=4, interleave_depth=6, header_redundancy=5,
        window_size_bytes=128*1024*1024),
    ("large",  "classified"): TransferProfile(num_passes=2, overhead_ratio=0.30,
        rs_n=136, rs_k=8, interleave_depth=8, header_redundancy=5,
        window_size_bytes=128*1024*1024),
}

def get_profile(file_size: int, criticality: str) -> TransferProfile:
    if criticality not in ("standard", "critical", "classified"):
        raise ValueError(f"Invalid criticality: {criticality}")
    if criticality == "classified":
        size_cat = _size_cat(file_size)
        return PROFILES[(size_cat, "classified")]
    return PROFILES[(_size_cat(file_size), criticality)]

def _size_cat(file_size: int) -> str:
    if file_size < 10 * 1024 * 1024:   return "small"
    if file_size < 1024**3:             return "medium"
    return "large"

# FIX G: Window Size Proportional to File Size
def get_window_size(file_size: int) -> int:
    """Proportional window sizing — small files = single window."""
    MB, GB = 1024*1024, 1024**3
    if file_size < GB:      return file_size   # single window up to 1GB
    return GB                                   # 1GB windows for larger files
