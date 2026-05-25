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

DEFAULT_CHUNK_SIZE = 512


from common.models import TransferProfile

@dataclass(frozen=True)
class Profile:
    """Wrapper for TransferProfile to add compatibility properties."""
    base: TransferProfile

    def __post_init__(self):
        if not (1 <= self.passes <= 2):              # ← hard cap at 2
            raise ValueError(f"passes must be 1–2, got {self.passes}")
        if not (0.10 <= self.overhead_ratio <= 0.30):
            raise ValueError(f"overhead_ratio out of range: {self.overhead_ratio}")

    @property
    def passes(self) -> int: return self.base.num_passes
    @property
    def num_passes(self) -> int: return self.base.num_passes
    @property
    def overhead_ratio(self) -> float: return self.base.overhead_ratio
    @property
    def rs_config(self) -> str: return f"RS({self.base.rs_n},{self.base.rs_k})"
    @property
    def rs_n(self) -> int: return self.base.rs_n
    @property
    def rs_k(self) -> int: return self.base.rs_k
    @property
    def interleave_depth(self) -> int: return self.base.interleave_depth
    @property
    def header_redundancy(self) -> int: return self.base.header_redundancy
    @property
    def window_size_bytes(self) -> int: return self.base.window_size_bytes
    
    @property
    def chunk_size_bytes(self) -> int:
        return DEFAULT_CHUNK_SIZE


from common.config import PROFILES as CONFIG_PROFILES

def get_profile(file_size_bytes: int, criticality: str) -> Profile:
    """
    Retrieve the transfer profile.
    """
    from common.config import get_profile as get_base_profile
    base = get_base_profile(file_size_bytes, criticality)
    return Profile(base=base)


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
