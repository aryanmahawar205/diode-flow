"""Profile selector — thin wrapper around config.get_profile()."""
from __future__ import annotations
from common.config import get_profile, get_window_size, PROFILES
from common.models import TransferProfile

def select_profile(file_size: int, criticality: str) -> TransferProfile:
    """Get transfer profile. Single entry point for all profile decisions."""
    return get_profile(file_size, criticality)

def select_window_size(file_size: int) -> int:
    """Get window size. Proportional — small files = single window."""
    return get_window_size(file_size)
