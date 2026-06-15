from __future__ import annotations

import argparse
import logging
import os
import sys

from common import state_writer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("sender")

import fountain
from sender.pipeline import run_sender


if __name__ == "__main__":

    p = argparse.ArgumentParser(
        description="Data Diode Sender"
    )

    p.add_argument(
        "--file",
        required=True,
        help="File to transfer"
    )

    p.add_argument(
        "--receiver-ip",
        required=True,
        help="Receiver IP address"
    )

    p.add_argument(
        "--security",
        default="standard",
        help="standard/critical/classified"
    )

    p.add_argument(
        "--pps",
        default=50000,
        type=int
    )

    p.add_argument(
        "--loss",
        default=0.0,
        type=float
    )

    p.add_argument(
        "--port",
        default=20000,
        type=int
    )

    args = p.parse_args()

    state_writer.clear_state()

    file_size = os.path.getsize(args.file)

    logger.info(
        f"Transferring: {args.file} "
        f"({file_size/1024**2:.2f} MB) "
        f"| security={args.security} "
        f"| pps={args.pps}"
    )

    ok = run_sender(
        args.file,
        (args.receiver_ip, args.port),
        args.security,
        args.pps,
        args.loss
    )

    sys.exit(0 if ok else 1)
