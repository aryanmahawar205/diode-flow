from __future__ import annotations

import os

DEFAULT_KEY = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def get_packet_mac_key() -> bytes:
    key = os.environ.get(
        "DIODE_PACKET_KEY",
        DEFAULT_KEY
    )

    return key.encode()