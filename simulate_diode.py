"""
End-to-end data diode simulator.
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

# Add root and data_diode to path
root_dir = str(Path(__file__).parent)
sys.path.insert(0, root_dir)
sys.path.insert(0, os.path.join(root_dir, "data_diode"))

from sender.pipeline import run_sender
from receiver.pipeline import run_receiver
from common.config import DEFAULT_UDP_PORT, LOOPBACK_ADDRESS

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
    parser.add_argument("--loss-rate", type=float, default=0.0, help="Packet loss rate (0.0 to 1.0)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: File {args.file} not found")
        sys.exit(1)

    # Ensure storage exists
    os.makedirs(args.storage, exist_ok=True)
    
    quit_event = multiprocessing.Event()
    
    receiver_proc = multiprocessing.Process(
        target=run_receiver,
        kwargs={
            "bind_addr": LOOPBACK_ADDRESS,
            "bind_port": args.port,
            "storage_dir": args.storage,
            "quit_event": quit_event
        }
    )
    
    sender_proc = multiprocessing.Process(
        target=run_sender,
        kwargs={
            "file_path": args.file,
            "target_addr": (LOOPBACK_ADDRESS, args.port),
            "criticality": args.criticality,
            "loss_rate": args.loss_rate
        }
    )
    
    logger.info("Starting simulation...")
    receiver_proc.start()
    time.sleep(1)
    
    sender_proc.start()
    sender_proc.join()
    logger.info("Sender finished.")
    
    # Wait for completion
    file_name = os.path.basename(args.file)
    timeout = 300
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(os.path.join(args.storage, file_name)):
            logger.info("SUCCESS! File found in storage.")
            break
        time.sleep(1)
        if not receiver_proc.is_alive():
            logger.error("Receiver died.")
            break
            
    quit_event.set()
    receiver_proc.join(timeout=5)
    if receiver_proc.is_alive():
        receiver_proc.terminate()
    
    logger.info("Simulation complete.")


if __name__ == "__main__":
    main()
