"""
tests/test_profile.py — Transfer Profile Selector Tests

Tests for sender/m5_profile.py:
- Profile table completeness
- File size categorization
- Profile retrieval
- Window size estimation
"""

import pytest
from data_diode.sender.m5_profile import (
    Profile,
    PROFILES,
    categorize_file_size,
    get_profile,
    get_window_size,
    SMALL_THRESHOLD,
    MEDIUM_THRESHOLD,
)


class TestProfile:
    """Test Profile dataclass."""
    
    def test_valid_profile(self):
        """Test creating valid profile."""
        p = Profile(
            passes=2,
            overhead_ratio=0.15,
            rs_config="RS(32,4)",
            interleave_depth=4,
            header_redundancy=3,
            window_size_bytes=64*1024*1024,
        )
        assert p.passes == 2
        assert p.overhead_ratio == 0.15
    
    def test_profile_validation_passes_range(self):
        """Test passes must be 1-3."""
        with pytest.raises(ValueError):
            Profile(passes=0, overhead_ratio=0.15, rs_config="RS(32,4)", interleave_depth=4, header_redundancy=3, window_size_bytes=64*1024*1024)
        
        with pytest.raises(ValueError):
            Profile(passes=5, overhead_ratio=0.15, rs_config="RS(32,4)", interleave_depth=4, header_redundancy=3, window_size_bytes=64*1024*1024)
    
    def test_profile_validation_overhead_range(self):
        """Test overhead_ratio must be 0.10-0.30."""
        with pytest.raises(ValueError):
            Profile(passes=2, overhead_ratio=0.05, rs_config="RS(32,4)", interleave_depth=4, header_redundancy=3, window_size_bytes=64*1024*1024)
        
        with pytest.raises(ValueError):
            Profile(passes=2, overhead_ratio=0.50, rs_config="RS(32,4)", interleave_depth=4, header_redundancy=3, window_size_bytes=64*1024*1024)


class TestProfileTable:
    """Test global PROFILES table."""
    
    def test_profile_count(self):
        """Test 7 profiles in table."""
        assert len(PROFILES) == 7
    
    def test_all_profiles_valid(self):
        """Test all profiles are valid Profile instances."""
        for key, profile in PROFILES.items():
            assert isinstance(key, tuple)
            assert len(key) == 2
            assert isinstance(profile, Profile)
    
    def test_profile_keys_coverage(self):
        """Test coverage of size × criticality combinations."""
        size_cats = {"small", "medium", "large", "any"}
        criticality_cats = {"standard", "critical", "classified"}
        
        keys = set(PROFILES.keys())
        
        # Should have: 3 sizes × 2 criticalities + classified
        # ("small", "standard"), ("small", "critical")
        # ("medium", "standard"), ("medium", "critical")
        # ("large", "standard"), ("large", "critical")
        # ("any", "classified")
        expected = {
            ("small", "standard"), ("small", "critical"),
            ("medium", "standard"), ("medium", "critical"),
            ("large", "standard"), ("large", "critical"),
            ("any", "classified"),
        }
        assert keys == expected


class TestFileSizeCategorization:
    """Test file size categorization."""
    
    def test_small_file(self):
        """Test files < 10 MB are 'small'."""
        assert categorize_file_size(1) == "small"
        assert categorize_file_size(1024) == "small"
        assert categorize_file_size(10 * 1024 * 1024 - 1) == "small"
    
    def test_medium_file(self):
        """Test files 10 MB – 1 GB are 'medium'."""
        assert categorize_file_size(10 * 1024 * 1024) == "medium"
        assert categorize_file_size(100 * 1024 * 1024) == "medium"
        assert categorize_file_size(1024 * 1024 * 1024 - 1) == "medium"
    
    def test_large_file(self):
        """Test files > 1 GB are 'large'."""
        assert categorize_file_size(1024 * 1024 * 1024) == "large"
        assert categorize_file_size(10 * 1024 * 1024 * 1024) == "large"


class TestGetProfile:
    """Test profile retrieval."""
    
    def test_get_small_standard(self):
        """Test retrieval of small/standard profile."""
        p = get_profile(1024 * 1024, "standard")
        assert p.passes == 1
        assert p.overhead_ratio == 0.20
        assert p.rs_config == "RS(16,2)"
    
    def test_get_medium_critical(self):
        """Test retrieval of medium/critical profile."""
        p = get_profile(100 * 1024 * 1024, "critical")
        assert p.passes == 3
        assert p.overhead_ratio == 0.15
        assert p.rs_config == "RS(32,6)"
    
    def test_get_large_standard(self):
        """Test retrieval of large/standard profile."""
        p = get_profile(5 * 1024 * 1024 * 1024, "standard")
        assert p.passes == 2
        assert p.rs_config == "RS(64,6)"
    
    def test_get_classified_overrides_size(self):
        """Test classified profile overrides file size."""
        p1 = get_profile(100, "classified")  # tiny file
        p2 = get_profile(100 * 1024 * 1024 * 1024, "classified")  # huge file
        
        # Both should have same profile (classified)
        assert p1 == p2
        assert p1.passes == 3
        assert p1.rs_config == "RS(32,8)"
    
    def test_invalid_criticality(self):
        """Test invalid criticality level."""
        with pytest.raises(ValueError):
            get_profile(1024, "invalid")
    
    def test_determinism(self):
        """Test profile retrieval is deterministic."""
        p1 = get_profile(50 * 1024 * 1024, "critical")
        p2 = get_profile(50 * 1024 * 1024, "critical")
        
        assert p1 == p2


class TestWindowSize:
    """Test window size estimation."""
    
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
    
    def test_default_ram(self):
        """Test default (no argument) uses 1 GB."""
        size = get_window_size()
        assert size == 64 * 1024 * 1024  # 1 GB is in 512 MB – 2 GB range
