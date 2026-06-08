"""
Main demo entry point.
Launches sender and receiver as two separate processes.
The receiver process NEVER communicates back to the sender.

# Run the UI separately:
#   streamlit run ui/streamlit_app.py
# Then run this script:
#   python run_demo.py --file test_files/small.txt
"""
from __future__ import annotations  
import argparse
import logging
import multiprocessing
import os
import sys
import time
from pathlib import Path
from common import state_writer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("demo")


def _receiver_proc(addr, port, storage_dir, timeout):
    import fountain   # triggers codec registration
    from receiver.pipeline import run_receiver
    success = run_receiver(addr, port, storage_dir, timeout)
    sys.exit(0 if success else 1)


def _sender_proc(file_path, addr, port, criticality, pps, loss):
    import fountain
    from sender.pipeline import run_sender
    success = run_sender(file_path, (addr, port), criticality, pps, loss)
    sys.exit(0 if success else 1)


def transfer(file_path: str, criticality: str = "standard",
             addr: str = "127.0.0.1", port: int = 20000,
             pps: int = 10000, loss: float = 0.0, timeout: int = 600) -> bool:

    # MONITORING RESET
    state_writer.clear_state()

    storage = "demo_output/storage"
    Path(storage).mkdir(parents=True, exist_ok=True)

    file_size = os.path.getsize(file_path)
    logger.info(f"Transferring: {file_path} ({file_size/1024**2:.2f} MB) "
                f"| security={criticality} | pps={pps}")

    rx = multiprocessing.Process(target=_receiver_proc,
                                  args=(addr, port, storage, timeout))
    tx = multiprocessing.Process(target=_sender_proc,
                                  args=(file_path, addr, port, criticality, pps, loss))

    rx.start()
    time.sleep(1.0)   # give receiver time to bind socket
    tx.start()

    tx.join(timeout=timeout)
    if tx.is_alive():
        logger.error("Sender timed out")
        tx.kill()
        rx.kill()
        return False

    rx.join(timeout=60)   # receiver may take a moment to finish assembly
    return rx.exitcode == 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Data Diode Demo")
    p.add_argument("--file",        required=True,            help="File to transfer")
    p.add_argument("--security",    default="standard",       help="standard/critical/classified")
    p.add_argument("--pps",         default=50000, type=int,  help="Packets per second")
    p.add_argument("--loss",        default=0.0,   type=float,help="Simulated packet loss rate (0.0-1.0)")
    p.add_argument("--port",        default=20000, type=int,  help="UDP port")
    p.add_argument("--timeout",     default=86400,  type=int,  help="Timeout in seconds")
    args = p.parse_args()

    ok = transfer(args.file, args.security, port=args.port,
                  pps=args.pps, loss=args.loss, timeout=args.timeout)
    sys.exit(0 if ok else 1)
