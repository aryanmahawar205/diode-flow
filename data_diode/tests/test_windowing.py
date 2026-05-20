"""
tests/test_windowing.py — File Windowing Tests

Tests for sender/m1_windowing.py:
- Window computation and boundaries
- File window reading
- Edge cases (empty, single-window, boundary alignment)
"""

import pytest
import tempfile
from pathlib import Path
from data_diode.sender.m1_windowing import Window, compute_windows, get_file_window


class TestWindow:
    """Test Window dataclass."""
    
    def test_valid_window(self):
        """Test creating valid window."""
        w = Window(window_id=0, start_byte=0, end_byte=1024, num_bytes=1024, is_last=False)
        assert w.window_id == 0
        assert w.num_bytes == 1024
    
    def test_window_validation_invalid_range(self):
        """Test start >= end."""
        with pytest.raises(ValueError):
            Window(window_id=0, start_byte=1024, end_byte=1024, num_bytes=0, is_last=False)
        
        with pytest.raises(ValueError):
            Window(window_id=0, start_byte=2000, end_byte=1000, num_bytes=-1000, is_last=False)
    
    def test_window_validation_mismatched_num_bytes(self):
        """Test num_bytes mismatch."""
        with pytest.raises(ValueError):
            Window(window_id=0, start_byte=0, end_byte=1024, num_bytes=512, is_last=False)


class TestComputeWindows:
    """Test window computation."""
    
    def test_single_window(self):
        """Test file smaller than window size."""
        file_size = 1000
        window_size = 10000
        
        windows = compute_windows(file_size, window_size)
        
        assert len(windows) == 1
        assert windows[0].window_id == 0
        assert windows[0].start_byte == 0
        assert windows[0].end_byte == 1000
        assert windows[0].num_bytes == 1000
        assert windows[0].is_last is True
    
    def test_exact_multiple_windows(self):
        """Test file exactly multiple of window size."""
        file_size = 10000
        window_size = 1000
        
        windows = compute_windows(file_size, window_size)
        
        assert len(windows) == 10
        
        for i, w in enumerate(windows):
            assert w.window_id == i
            assert w.start_byte == i * 1000
            assert w.end_byte == (i + 1) * 1000
            assert w.num_bytes == 1000
            assert w.is_last == (i == 9)
    
    def test_partial_last_window(self):
        """Test file not exact multiple of window size."""
        file_size = 2500
        window_size = 1000
        
        windows = compute_windows(file_size, window_size)
        
        assert len(windows) == 3
        assert windows[0].end_byte == 1000
        assert windows[1].end_byte == 2000
        assert windows[2].end_byte == 2500
        assert windows[2].num_bytes == 500
        assert windows[2].is_last is True
    
    def test_large_file_many_windows(self):
        """Test large file with many windows."""
        file_size = 1024 * 1024 * 1024  # 1 GB
        window_size = 64 * 1024 * 1024   # 64 MB
        
        windows = compute_windows(file_size, window_size)
        
        assert len(windows) == 16
        total_bytes = sum(w.num_bytes for w in windows)
        assert total_bytes == file_size
        assert windows[-1].is_last is True
        assert all(not w.is_last for w in windows[:-1])
    
    def test_validation_invalid_file_size(self):
        """Test invalid file size."""
        with pytest.raises(ValueError):
            compute_windows(0, 1000)
        
        with pytest.raises(ValueError):
            compute_windows(-1, 1000)
    
    def test_validation_invalid_window_size(self):
        """Test invalid window size."""
        with pytest.raises(ValueError):
            compute_windows(1000, 0)
        
        with pytest.raises(ValueError):
            compute_windows(1000, -1)


class TestGetFileWindow:
    """Test file window reading."""
    
    def test_read_full_file_single_window(self):
        """Test reading entire file as single window."""
        content = b"Hello, World!"
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            path = Path(temp_path)
            window = Window(window_id=0, start_byte=0, end_byte=len(content), num_bytes=len(content), is_last=True)
            
            data = get_file_window(path, window)
            
            assert data == content
        finally:
            Path(temp_path).unlink()
    
    def test_read_middle_window(self):
        """Test reading middle window."""
        content = b"0123456789ABCDEF"
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            path = Path(temp_path)
            window = Window(window_id=1, start_byte=5, end_byte=10, num_bytes=5, is_last=False)
            
            data = get_file_window(path, window)
            
            assert data == b"56789"
        finally:
            Path(temp_path).unlink()
    
    def test_read_multiple_windows(self):
        """Test reading entire file as multiple windows."""
        content = b"AAABBBCCCDDDEEE"
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            path = Path(temp_path)
            windows = [
                Window(window_id=0, start_byte=0, end_byte=3, num_bytes=3, is_last=False),
                Window(window_id=1, start_byte=3, end_byte=6, num_bytes=3, is_last=False),
                Window(window_id=2, start_byte=6, end_byte=15, num_bytes=9, is_last=True),
            ]
            
            data = [get_file_window(path, w) for w in windows]
            reconstructed = b"".join(data)
            
            assert reconstructed == content
        finally:
            Path(temp_path).unlink()
    
    def test_read_nonexistent_file(self):
        """Test reading nonexistent file."""
        path = Path("/nonexistent/file.bin")
        window = Window(window_id=0, start_byte=0, end_byte=100, num_bytes=100, is_last=True)
        
        with pytest.raises(IOError):
            get_file_window(path, window)
    
    def test_read_beyond_file_end(self):
        """Test reading past EOF."""
        content = b"SHORT"
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            path = Path(temp_path)
            window = Window(window_id=0, start_byte=0, end_byte=100, num_bytes=100, is_last=True)
            
            with pytest.raises(IOError):
                get_file_window(path, window)
        finally:
            Path(temp_path).unlink()
