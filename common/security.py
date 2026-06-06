from __future__ import annotations

import os

DEFAULT_KEY = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

PACKET_MAC_KEY = (
    os.environ.get("DIODE_PACKET_KEY", DEFAULT_KEY)
    .encode()
)