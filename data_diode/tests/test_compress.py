"""
tests/test_compress.py — Tests for streaming lz4 compression/decompression.
"""

import os
import pytest
from data_diode.sender.m0_compress import compress_file, should_compress
from data_diode.receiver.m24_decompress import decompress_file

def test_should_compress():
    assert should_compress("test.txt") is True
    assert should_compress("test.csv") is True
    assert should_compress("photo.jpg") is False
    assert should_compress("video.mp4") is False
    assert should_compress("archive.zip") is False

def test_compress_roundtrip_text(tmp_path):
    # 1. Create a highly compressible text file
    input_file = tmp_path / "test.txt"
    content = b"The quick brown fox jumps over the lazy dog\n" * 1000
    input_file.write_bytes(content)
    
    compressed_file = tmp_path / "test.txt.lz4"
    decompressed_file = tmp_path / "test_out.txt"
    
    # 2. Compress
    result = compress_file(str(input_file), str(compressed_file))
    
    assert result.algorithm == "lz4"
    assert result.original_size == len(content)
    assert result.compressed_size < result.original_size
    assert os.path.exists(str(compressed_file))
    
    # 3. Decompress
    success = decompress_file(
        str(compressed_file),
        str(decompressed_file),
        algorithm=result.algorithm,
        expected_sha256=result.original_sha256
    )
    
    assert success is True
    assert os.path.exists(str(decompressed_file))
    assert decompressed_file.read_bytes() == content
    # compressed file should be removed by decompress_file
    assert not os.path.exists(str(compressed_file))

def test_compress_skip_binary(tmp_path):
    # 1. Create a "jpg" file (which should skip compression)
    input_file = tmp_path / "image.jpg"
    content = os.urandom(1024)
    input_file.write_bytes(content)
    
    output_file = tmp_path / "image_sent.jpg"
    
    # 2. Compress (should just copy)
    result = compress_file(str(input_file), str(output_file))
    
    assert result.algorithm == "none"
    assert result.original_size == result.compressed_size
    assert result.compression_ratio == 1.0
    assert output_file.read_bytes() == content

def test_decompress_sha_mismatch(tmp_path):
    input_file = tmp_path / "fail.txt"
    input_file.write_bytes(b"some data")
    
    compressed_file = tmp_path / "fail.txt.lz4"
    decompressed_file = tmp_path / "fail_out.txt"
    
    result = compress_file(str(input_file), str(compressed_file))
    
    # Attempt decompress with wrong SHA
    success = decompress_file(
        str(compressed_file),
        str(decompressed_file),
        algorithm="lz4",
        expected_sha256="wrong_sha"
    )
    
    assert success is False
