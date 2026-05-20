"""
sender/m5_profile.py — Transfer Profile Selector

Role:
Single configuration controller that determines all tunable parameters for a
transfer based on file size and criticality level. This is the only place where
robustness strategy is defined — changing a profile here propagates to all
downstream modules (m0, m1, m4, m6, m7, m8, m9).

Design:
- 9 predefined profiles: 3 file size categories × 3 criticality levels
- Each profile encodes: passes, overhead_ratio, RS config, interleave_depth, header_redundancy
- All downstream modules consume one profile for a given transfer
- New robustness strategies can be added by extending the PROFILES table

Profile table keys:
  ("small",  "standard")  → 1 pass, 20% overhead, RS(16,2),  interleave=2
  ("small",  "critical")  → 2 passes, 20% overhead, RS(16,4), interleave=3
  ("medium", "standard")  → 2 passes, 15% overhead, RS(32,4), interleave=4
  ("medium", "critical")  → 3 passes, 15% overhead, RS(32,6), interleave=5
  ("large",  "standard")  → 2 passes, 20% overhead, RS(64,6), interleave=6
  ("large",  "critical")  → 3 passes, 15% overhead, RS(64,8), interleave=6
  ("any",    "classified") → 3 passes, 25% overhead, RS(32,8), interleave=8

Size thresholds:
  small  < 10 MB
  medium 10 MB – 1 GB
  large  > 1 GB

Criticality levels:
  "standard"   → Best effort, reasonable redundancy
  "critical"   → High reliability, more passes + RS parity
  "classified" → Maximum reliability, maximum overhead

Window sizing (independent of criticality):
  < 512 MB RAM   → 32 MB windows
  512 MB – 2 GB  → 64 MB windows (default)
  > 2 GB         → 128 MB windows
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Profile:
    """Complete transfer profile with all tuning parameters."""
    passes: int                    # Number of fountain encoding passes (1-3)
    overhead_ratio: float          # Overhead per pass (0.15-0.25)
    rs_config: str                 # RS(n, k) string, e.g., "RS(16,2)"
    interleave_depth: int          # Stride for packet interleaving (2-8)
    header_redundancy: int         # How many times to send manifest (3-5)
    window_size_bytes: int         # Bytes per window (32 MB – 128 MB)
    
    def __post_init__(self):
        """Validate profile parameters."""
        if not (1 <= self.passes <= 3):
            raise ValueError(f"passes must be 1–3, got {self.passes}")
        if not (0.10 <= self.overhead_ratio <= 0.30):
            raise ValueError(f"overhead_ratio must be 0.10–0.30, got {self.overhead_ratio}")
        if not (2 <= self.interleave_depth <= 8):
            raise ValueError(f"interleave_depth must be 2–8, got {self.interleave_depth}")
        if not (3 <= self.header_redundancy <= 5):
            raise ValueError(f"header_redundancy must be 3–5, got {self.header_redundancy}")
        if not (32 * 1024 * 1024 <= self.window_size_bytes <= 128 * 1024 * 1024):
            raise ValueError(f"window_size_bytes must be 32–128 MB, got {self.window_size_bytes}")


# Global profile table — the single source of truth for robustness strategy
PROFILES: dict[Tuple[str, str], Profile] = {
    ("small", "standard"):    Profile(passes=1, overhead_ratio=0.20, rs_config="RS(16,2)",  interleave_depth=2,  header_redundancy=3, window_size_bytes=64*1024*1024),
    ("small", "critical"):    Profile(passes=2, overhead_ratio=0.20, rs_config="RS(16,4)",  interleave_depth=3,  header_redundancy=5, window_size_bytes=64*1024*1024),
    ("medium", "standard"):   Profile(passes=2, overhead_ratio=0.15, rs_config="RS(32,4)",  interleave_depth=4,  header_redundancy=3, window_size_bytes=64*1024*1024),
    ("medium", "critical"):   Profile(passes=3, overhead_ratio=0.15, rs_config="RS(32,6)",  interleave_depth=5,  header_redundancy=5, window_size_bytes=64*1024*1024),
    ("large", "standard"):    Profile(passes=2, overhead_ratio=0.20, rs_config="RS(64,6)",  interleave_depth=6,  header_redundancy=3, window_size_bytes=64*1024*1024),
    ("large", "critical"):    Profile(passes=3, overhead_ratio=0.15, rs_config="RS(64,8)",  interleave_depth=6,  header_redundancy=5, window_size_bytes=64*1024*1024),
    ("any", "classified"):    Profile(passes=3, overhead_ratio=0.25, rs_config="RS(32,8)",  interleave_depth=8,  header_redundancy=5, window_size_bytes=64*1024*1024),
}

# Size thresholds for categorization
SMALL_THRESHOLD = 10 * 1024 * 1024              # 10 MB
MEDIUM_THRESHOLD = 1024 * 1024 * 1024           # 1 GB


def categorize_file_size(file_bytes: int) -> str:
    """Categorize file size: 'small', 'medium', or 'large'."""
    if file_bytes < SMALL_THRESHOLD:
        return "small"
    elif file_bytes < MEDIUM_THRESHOLD:
        return "medium"
    else:
        return "large"


def get_profile(file_size_bytes: int, criticality: str) -> Profile:
    """
    Retrieve the transfer profile for a given file size and criticality level.
    
    Args:
        file_size_bytes: Byte count of the file to transfer
        criticality: One of "standard", "critical", "classified"
    
    Returns:
        Profile with all tuning parameters
    
    Raises:
        ValueError: If criticality is invalid or profile not found
    """
    if criticality not in ("standard", "critical", "classified"):
        raise ValueError(f"criticality must be 'standard', 'critical', or 'classified', got {criticality!r}")
    
    # Classified transfers always use the "classified" profile regardless of file size
    if criticality == "classified":
        return PROFILES[("any", "classified")]
    
    # Standard/critical: categorize by file size
    size_cat = categorize_file_size(file_size_bytes)
    profile_key = (size_cat, criticality)
    
    if profile_key not in PROFILES:
        raise ValueError(f"No profile for file_size={file_size_bytes}, criticality={criticality!r}")
    
    return PROFILES[profile_key]


def get_window_size(available_ram_mb: int = 1024) -> int:
    """
    Determine window size based on available RAM budget.
    
    Args:
        available_ram_mb: Estimated available RAM in MB (default 1 GB)
    
    Returns:
        Window size in bytes (32 MB, 64 MB, or 128 MB)
    
    Rationale:
        - 32 MB window at default 1200 B/chunk ≈ 27k chunks → ~675k decoder nodes (manageable)
        - 64 MB window → ~53k chunks → ~1.3M decoder nodes (default)
        - 128 MB window → ~106k chunks → ~2.6M decoder nodes (large systems)
    """
    if available_ram_mb < 512:
        return 32 * 1024 * 1024
    elif available_ram_mb < 2048:
        return 64 * 1024 * 1024
    else:
        return 128 * 1024 * 1024
