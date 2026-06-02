"""End-to-end integration tests."""
from __future__ import annotations
import os
import shutil
import pytest
from run_demo import transfer


@pytest.fixture
def test_env(tmp_path):
    storage = tmp_path / "storage"
    test_files = tmp_path / "test_files"
    test_files.mkdir()
    
    # Create small test file
    small_file = test_files / "small.txt"
    small_file.write_text("hello world\n" * 100)
    
    return {"storage": storage, "test_files": test_files, "small_file": small_file}


def test_e2e_small_file(test_env):
    file_path = str(test_env["small_file"])
    
    # Run transfer
    # We use a different port to avoid collisions
    success = transfer(file_path, port=20001, timeout=60)
    assert success
    
    # Verify file exists in storage
    storage_dir = "demo_output/storage"
    files = os.listdir(storage_dir)
    # The file in storage might have the same name or a different one depending on how run_demo works
    # Actually run_demo always uses demo_output/storage
    
    import hashlib
    def sha256(p):
        h = hashlib.sha256()
        with open(p,'rb') as f:
            while c := f.read(65536): h.update(c)
        return h.hexdigest()
    
    src_hash = sha256(file_path)
    # Find received file (most recent one)
    rx_files = sorted([f for f in os.listdir(storage_dir) if not f.endswith('_receipt.json')], 
                      key=lambda x: os.path.getmtime(os.path.join(storage_dir, x)))
    dst_hash = sha256(os.path.join(storage_dir, rx_files[-1]))
    
    assert src_hash == dst_hash
