import os
import tempfile
import hashlib
from pathlib import Path
import pytest
from sender.m0_compress import (
    compress_file, 
    should_compress, 
    compute_sha256_streaming,
    CompressionResult
)
from receiver.m24_decompress import decompress_file

def test_should_compress_logic():
    assert should_compress("test.txt") is True
    assert should_compress("data.csv") is True
    assert should_compress("app.log") is True
    assert should_compress("image.jpg") is False
    assert should_compress("video.mp4") is False
    assert should_compress("archive.zip") is False
    assert should_compress("photo.JPEG") is False

def test_compute_sha256_streaming():
    data = b"hello world" * 1000
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    
    try:
        expected = hashlib.sha256(data).hexdigest()
        actual = compute_sha256_streaming(tmp_path)
        assert actual == expected
    finally:
        os.unlink(tmp_path)

def test_compression_roundtrip_repetitive_text():
    # Repetitive text should compress well
    data = b"This is a repetitive line of text. " * 10000 
    
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fin, \
         tempfile.NamedTemporaryFile(suffix=".lz4", delete=False) as fmid, \
         tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fout:
        
        fin.write(data)
        fin.close()
        fmid.close()
        fout.close()
        
        input_path = fin.name
        compressed_path = fmid.name
        output_path = fout.name
    
    try:
        # 1. Compress
        result = compress_file(input_path, compressed_path)
        assert result.algorithm == "lz4"
        assert result.compression_ratio > 1.0
        assert os.path.exists(compressed_path)
        assert os.path.getsize(compressed_path) < len(data)
        
        # 2. Decompress
        success = decompress_file(
            compressed_path=compressed_path,
            output_path=output_path,
            algorithm=result.algorithm,
            expected_sha256=result.original_sha256
        )
        
        assert success is True
        assert os.path.exists(output_path)
        with open(output_path, 'rb') as f:
            decompressed_data = f.read()
        assert decompressed_data == data
        
        # Check that compressed file was deleted by decompress_file
        assert not os.path.exists(compressed_path)
        
    finally:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(compressed_path): os.unlink(compressed_path)
        if os.path.exists(output_path): os.unlink(output_path)

def test_compression_none_algorithm():
    # JPG should skip compression
    data = b"fake jpg data"
    
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as fin, \
         tempfile.NamedTemporaryFile(suffix=".copy", delete=False) as fmid, \
         tempfile.NamedTemporaryFile(suffix=".out", delete=False) as fout:
        
        fin.write(data)
        fin.close()
        fmid.close()
        fout.close()
        
        input_path = fin.name
        compressed_path = fmid.name
        output_path = fout.name
        
    try:
        # 1. Compress (should just copy)
        result = compress_file(input_path, compressed_path)
        assert result.algorithm == "none"
        assert result.compression_ratio == 1.0
        
        # 2. Decompress (should just copy)
        success = decompress_file(
            compressed_path=compressed_path,
            output_path=output_path,
            algorithm=result.algorithm,
            expected_sha256=result.original_sha256
        )
        
        assert success is True
        with open(output_path, 'rb') as f:
            assert f.read() == data
            
    finally:
        if os.path.exists(input_path): os.unlink(input_path)
        if os.path.exists(compressed_path): os.unlink(compressed_path)
        if os.path.exists(output_path): os.unlink(output_path)
