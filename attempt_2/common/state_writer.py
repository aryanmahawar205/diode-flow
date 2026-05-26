"""
Thread-safe and atomic state writer for monitoring the data diode system.
Both sender and receiver pipelines report their status here.
"""
from __future__ import annotations
import json
import os
import threading
import time
from pathlib import Path

# Absolute path to ensure consistency across different working directories
BASE_DIR = Path(__file__).parent.parent
STATE_FILE = str(BASE_DIR / "demo_output" / "transfer_state.json")
LOCK = threading.Lock()

def _write_state(state: dict) -> None:
    """Atomic write with unique temp file to prevent race conditions."""
    state["last_updated"] = time.time()
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    # Unique temp file for this thread/process
    tmp_file = f"{STATE_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_file, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_file, STATE_FILE)
    except Exception:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        raise

def _read_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def init_state(transfer_id, file_name, total_windows, criticality,
               file_path, original_size_mb, compression_algorithm):
    with LOCK:
        state = {
            "transfer_id": transfer_id,
            "file_name": file_name,
            "total_windows": total_windows,
            "criticality": criticality,
            "file_path": str(file_path),
            "original_size_mb": original_size_mb,
            "compression_algorithm": compression_algorithm,
            "overall_state": "RECEIVING",
            "sender": {
                "windows_sent": 0,
                "total_packets_sent": 0,
                "bytes_transmitted_mb": 0,
                "compressed_size_mb": 0,
                "compression_ratio": 1.0,
                "elapsed_s": 0,
                "eta_str": "calculating...",
                "status": "idle"
            },
            "receiver": {
                "windows_decoded": 0,
                "total_packets_rx": 0,
                "fountain_recovered_chunks": 0,
                "rs_recovered_chunks": 0,
                "failed_chunks": 0,
                "elapsed_s": 0,
                "status": "idle",
                "sha256_match": None,
                "storage_path": None
            },
            "warnings": [],
            "errors": []
        }
        _write_state(state)

def update_sender(windows_sent, total_packets_sent, bytes_transmitted_mb,
                  compressed_size_mb, compression_ratio, elapsed_s,
                  eta_str, status):
    with LOCK:
        state = _read_state()
        if not state: return
        state["sender"].update({
            "windows_sent": windows_sent,
            "total_packets_sent": total_packets_sent,
            "bytes_transmitted_mb": bytes_transmitted_mb,
            "compressed_size_mb": compressed_size_mb,
            "compression_ratio": compression_ratio,
            "elapsed_s": elapsed_s,
            "eta_str": eta_str,
            "status": status
        })
        _write_state(state)

def update_receiver(windows_decoded, total_packets_rx,
                    fountain_recovered_chunks, rs_recovered_chunks,
                    failed_chunks, elapsed_s, status,
                    sha256_match=None, storage_path=None):
    with LOCK:
        state = _read_state()
        if not state: return
        state["receiver"].update({
            "windows_decoded": windows_decoded,
            "total_packets_rx": total_packets_rx,
            "fountain_recovered_chunks": fountain_recovered_chunks,
            "rs_recovered_chunks": rs_recovered_chunks,
            "failed_chunks": failed_chunks,
            "elapsed_s": elapsed_s,
            "status": status
        })
        if sha256_match is not None:
            state["receiver"]["sha256_match"] = sha256_match
        if storage_path is not None:
            state["receiver"]["storage_path"] = str(storage_path)
        _write_state(state)

def set_overall_state(state_str):
    with LOCK:
        state = _read_state()
        if not state: return
        state["overall_state"] = state_str
        _write_state(state)

def add_warning(message):
    with LOCK:
        state = _read_state()
        if not state: return
        warnings = state.get("warnings", [])
        warnings.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        state["warnings"] = warnings[-20:]
        _write_state(state)

def add_error(message):
    with LOCK:
        state = _read_state()
        if not state: return
        errors = state.get("errors", [])
        errors.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        state["errors"] = errors[-20:]
        _write_state(state)

def clear_state():
    with LOCK:
        state = {
            "overall_state": "IDLE",
            "sender": {
                "windows_sent": 0,
                "total_packets_sent": 0,
                "bytes_transmitted_mb": 0,
                "compressed_size_mb": 0,
                "compression_ratio": 1.0,
                "elapsed_s": 0,
                "eta_str": "—",
                "status": "idle"
            },
            "receiver": {
                "windows_decoded": 0,
                "total_packets_rx": 0,
                "fountain_recovered_chunks": 0,
                "rs_recovered_chunks": 0,
                "failed_chunks": 0,
                "elapsed_s": 0,
                "status": "idle",
                "sha256_match": None,
                "storage_path": None
            },
            "warnings": [],
            "errors": []
        }
        _write_state(state)
