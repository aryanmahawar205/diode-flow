"""
tests/test_profile.py — Transfer Profile Selector Tests
"""

import pytest
from sender.m5_profile import get_profile, get_window_size, Profile
from common.config import PROFILES

class TestProfileWrapper:
    """Test the Profile wrapper in m5_profile.py."""
    
    def test_profile_wrapper_properties(self):
        """Test that wrapper exposes base properties correctly."""
        p = get_profile(1000, "standard")
        assert isinstance(p, Profile)
        assert p.num_passes == p.base.num_passes
        assert p.rs_n == p.base.rs_n
        assert p.rs_k == p.base.rs_k
        assert p.window_size_bytes == p.base.window_size_bytes

class TestGetProfile:
    """Test profile retrieval."""
    
    def test_get_small_standard(self):
        """Test retrieval of small/standard profile."""
        p = get_profile(1024 * 1024, "standard")
        assert p.num_passes == 1
        assert p.rs_n == 16
        assert p.rs_k == 14
    
    def test_get_medium_critical(self):
        """Test retrieval of medium/critical profile."""
        p = get_profile(100 * 1024 * 1024, "critical")
        assert p.num_passes == 2
        assert p.rs_n == 32
        assert p.rs_k == 26
    
    def test_get_large_standard(self):
        """Test retrieval of large/standard profile."""
        p = get_profile(5 * 1024 * 1024 * 1024, "standard")
        assert p.num_passes == 1
        assert p.rs_n == 64
        assert p.rs_k == 60

    def test_invalid_criticality(self):
        """Test invalid criticality level."""
        with pytest.raises(ValueError):
            get_profile(1024, "invalid")

class TestWindowSize:
    """Test window size estimation based on RAM."""
    
    def test_small_ram_small_window(self):
        """Test < 512 MB RAM → 32 MB windows."""
        size = get_window_size(available_ram_mb=256)
        assert size == 32 * 1024 * 1024
    
    def test_medium_ram_medium_window(self):
        """Test 512 MB – 2 GB RAM → 64 MB windows."""
        size = get_window_size(available_ram_mb=1024)
        assert size == 64 * 1024 * 1024
    
    def test_large_ram_large_window(self):
        """Test > 2 GB RAM → 128 MB windows."""
        size = get_window_size(available_ram_mb=4096)
        assert size == 128 * 1024 * 1024
