"""
End-to-end data diode simulator.

Launches sender and receiver as two independent processes
communicating over UDP loopback.
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Add data_diode to path
sys.path.insert(0, str(Path(__file__).parent))

from data_diode.sender.pipeline import run_sender
from data_diode.receiver.pipeline import run_receiver
from data_diode.common.config import DEFAULT_UDP_PORT, LOOPBACK_ADDRESS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("simulate_diode")


def main():
    parser = argparse.ArgumentParser(description="Data Diode Simulator")
    parser.add_argument("file", help="File to transfer")
    parser.add_argument("--criticality", choices=["standard", "critical", "classified"], default="standard")
    parser.add_argument("--port", type=int, default=DEFAULT_UDP_PORT)
    parser.add_argument("--storage", default="demo_output/storage")
    parser.add_argument("--secret", default="S" * 32)
    parser.add_argument("--loss-rate", type=float, default=0.0, help="Packet loss rate (0.0 to 1.0)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: File {args.file} not found")
        sys.exit(1)

    # Ensure storage exists
    os.makedirs(args.storage, exist_ok=True)
    
    # Shared secret as bytes
    shared_secret = args.secret.encode() if isinstance(args.secret, str) else args.secret
    if len(shared_secret) != 32:
        print("Error: Shared secret must be exactly 32 bytes")
        sys.exit(1)

    # Use multiprocessing to run sender and receiver in separate processes
    # They will communicate ONLY via UDP loopback
    
    # Event to signal receiver to stop (optional)
    quit_event = multiprocessing.Event()
    
    receiver_proc = multiprocessing.Process(
        target=run_receiver,
        kwargs={
            "bind_addr": LOOPBACK_ADDRESS,
            "bind_port": args.port,
            "storage_dir": args.storage,
            "shared_secret": shared_secret,
            "quit_event": quit_event
        }
    )
    
    sender_proc = multiprocessing.Process(
        target=run_sender,
        kwargs={
            "file_path": args.file,
            "target_addr": (LOOPBACK_ADDRESS, args.port),
            "criticality": args.criticality,
            "shared_secret": shared_secret,
            "loss_rate": args.loss_rate
        }
    )
    
    logger.info("Starting simulation...")
    receiver_proc.start()
    time.sleep(1)  # Give receiver time to bind
    
    sender_proc.start()
    
    # Wait for sender to finish
    sender_proc.join()
    logger.info("Sender process finished.")
    
    # Give receiver some time to finish decoding last windows
    # Dynamically poll the storage directory instead of fixed sleep
    file_name = os.path.basename(args.file)
    timeout = 120
    start_wait = time.time()
    
    while time.time() - start_wait < timeout:
        found = False
        try:
            for f in os.listdir(args.storage):
                if f.endswith("_" + file_name):
                    found = True
                    break
        except FileNotFoundError:
            pass
            
        if found:
            logger.info("File successfully verified and stored. Receiver finished.")
            break
            
        time.sleep(1)
        
        # Also check if receiver crashed
        if not receiver_proc.is_alive():
            logger.error("Receiver process died unexpectedly.")
            break
    
    quit_event.set()
    receiver_proc.join(timeout=5)
    if receiver_proc.is_alive():
        receiver_proc.terminate()
    
    logger.info("Simulation finished.")


if __name__ == "__main__":
    main()
