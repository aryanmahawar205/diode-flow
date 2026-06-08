from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

import fountain
from receiver.pipeline import run_receiver


if __name__ == "__main__":

    p = argparse.ArgumentParser(
        description="Data Diode Receiver"
    )

    p.add_argument(
        "--bind",
        default="0.0.0.0"
    )

    p.add_argument(
        "--port",
        default=20000,
        type=int
    )

    p.add_argument(
        "--storage",
        default="demo_output/storage"
    )

    p.add_argument(
        "--timeout",
        default=86400,
        type=int
    )

    args = p.parse_args()

    Path(args.storage).mkdir(
        parents=True,
        exist_ok=True
    )

    ok = run_receiver(
        args.bind,
        args.port,
        args.storage,
        args.timeout
    )

    sys.exit(0 if ok else 1)