import sys
import os
import json
import subprocess
import time
from pathlib import Path
from streamlit_autorefresh import st_autorefresh

import streamlit as st

root_dir = Path(__file__).parent.parent

if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from common import state_writer

STATE_FILE = root_dir / "demo_output" / "transfer_state.json"

st.set_page_config(
    page_title="Data Diode Control Center",
    page_icon="🛰️",
    layout="wide"
)

st_autorefresh(
    interval=1000,
    key="diode_autorefresh"
)

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def load_state():
    if not STATE_FILE.exists():
        return None

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def badge(text, color):
    return (
        f"<span style='padding:6px 12px;"
        f"border-radius:6px;"
        f"background:{color};"
        f"color:white;"
        f"font-weight:bold;'>"
        f"{text}</span>"
    )


def state_badge(state):
    colors = {
        "IDLE": "#666666",
        "RECEIVING": "#1565c0",
        "SENDING": "#1565c0",
        "ENCODING_RS": "#00838f",
        "DECODING": "#ef6c00",
        "VERIFYING": "#f9a825",
        "ACCEPTED": "#2e7d32",
        "FAILED": "#c62828",
    }

    return badge(
        state,
        colors.get(state, "#666666")
    )


state = load_state()

# ---------------------------------------------------------
# HEADER
# ---------------------------------------------------------

st.title("🛰️ Data Diode Control Center")

st.caption(
    "One-Way Secure Transfer System"
)

st.divider()

# ---------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------

with st.sidebar:

    st.header("Transfer Configuration")

    file_path = st.text_input(
        "Local File Path",
        placeholder=r"D:\files\archive.iso"
    )

    security_level = st.selectbox(
        "Security Level",
        ["standard", "critical", "classified"]
    )

    pps = st.number_input(
        "Packets Per Second",
        value=50000,
        min_value=1000,
        max_value=500000,
        step=1000
    )

    loss = st.slider(
        "Packet Loss Simulator",
        0.0,
        0.50,
        0.0,
        0.01
    )

    ui_key = st.text_input(
        "BLAKE3 Key",
        type="password"
    )

    start_transfer = st.button(
        "🚀 START TRANSFER",
        use_container_width=True
    )

    st.divider()

    if st.button(
        "🗑️ Clear Transfer State",
        use_container_width=True
    ):
        state_writer.clear_state()
        st.rerun()

    st.divider()

    st.info(
        "Receiver never transmits data back."
    )

    st.caption("Protocol v1.0")


if start_transfer:

    if not file_path:
        st.error("Please provide a file path")
        st.stop()

    if not os.path.exists(file_path):
        st.error(f"File not found: {file_path}")
        st.stop()

    env = os.environ.copy()

    if ui_key.strip():
        env["DIODE_PACKET_KEY"] = ui_key.strip()

    cmd = [
        sys.executable,
        str(root_dir / "run_demo.py"),
        "--file",
        file_path,
        "--security",
        security_level,
        "--pps",
        str(pps),
        "--loss",
        str(loss),
    ]

    subprocess.Popen(
        cmd,
        cwd=root_dir,
        env=env
    )

    st.success("Transfer started")
    
# ---------------------------------------------------------
# NO ACTIVE TRANSFER
# ---------------------------------------------------------

if not state:

    st.warning(
        "State file not found."
    )

    st.stop()

if state.get("overall_state") == "IDLE":

    st.info(
        "Waiting for transfer..."
    )

    if st.button(
        "Clear State",
        use_container_width=True
    ):
        state_writer.clear_state()

    st.stop()

# ---------------------------------------------------------
# TOP STATUS
# ---------------------------------------------------------

transfer_id = state.get("transfer_id", "----")
file_name = state.get("file_name", "----")
overall_state = state.get("overall_state", "IDLE")

last_updated = state.get("last_updated", 0)
updated_ago = int(time.time() - last_updated)

st.markdown(
    f"""
    **Transfer:** `{transfer_id[:8]}`

    **File:** `{file_name}`

    {state_badge(overall_state)}

    Updated {updated_ago}s ago
    """,
    unsafe_allow_html=True
)

st.divider()

# ---------------------------------------------------------
# SECURITY DASHBOARD
# ---------------------------------------------------------

st.subheader("Security")

sec1, sec2, sec3, sec4 = st.columns(4)

security = state.get("security", {})

sec1.metric(
    "ED25519 Signature",
    "Verified"
    if security.get("manifest_verified")
    else "Pending"
)

sec2.metric(
    "BLAKE3-MAC Packets",
    f"{security.get('mac_verified_packets',0):,}"
)

sec3.metric(
    "Compressed SHA256",
    "Verified"
    if security.get("compressed_sha_verified")
    else "Pending"
)

sec4.metric(
    "Original SHA256",
    "Verified"
    if security.get("original_sha_verified")
    else "Pending"
)

st.divider()

# ---------------------------------------------------------
# MAIN PANELS
# ---------------------------------------------------------

sender_col, receiver_col = st.columns(2)

# ---------------------------------------------------------
# SENDER
# ---------------------------------------------------------

with sender_col:

    st.subheader("Sender")

    sender = state.get("sender", {})

    st.markdown(
        state_badge(
            sender.get(
                "status",
                "idle"
            ).upper()
        ),
        unsafe_allow_html=True
    )

    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)

    c1.metric(
        "Original Size",
        f"{state.get('original_size_mb',0):.2f} MB"
    )

    c2.metric(
        "Compressed Size",
        f"{sender.get('compressed_size_mb',0):.2f} MB"
    )

    c3.metric(
        "Packets Sent",
        f"{sender.get('total_packets_sent',0):,}"
    )

    c4.metric(
        "Data Sent",
        f"{sender.get('bytes_transmitted_mb',0):.2f} MB"
    )

    total_windows = max(
        state.get("total_windows", 1),
        1
    )

    sent_windows = sender.get(
        "windows_sent",
        0
    )

    progress = min(
        sent_windows / total_windows,
        1.0
    )

    st.progress(progress)

    st.write(
        f"Windows: {sent_windows}/{total_windows}"
    )

    st.write(
        f"Elapsed: {sender.get('elapsed_s',0):.1f}s"
    )

    st.write(
        f"ETA: {sender.get('eta_str','-')}"
    )

# ---------------------------------------------------------
# RECEIVER
# ---------------------------------------------------------

with receiver_col:

    st.subheader("Receiver")

    receiver = state.get(
        "receiver",
        {}
    )

    st.markdown(
        state_badge(
            receiver.get(
                "status",
                "idle"
            ).upper()
        ),
        unsafe_allow_html=True
    )

    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)

    c1.metric(
        "Packets Received",
        f"{receiver.get('total_packets_rx',0):,}"
    )

    c2.metric(
        "Windows Decoded",
        receiver.get(
            "windows_decoded",
            0
        )
    )

    c3.metric(
        "Fountain Recovery",
        receiver.get(
            "fountain_recovered_chunks",
            0
        )
    )

    c4.metric(
        "RS Recovery",
        receiver.get(
            "rs_recovered_chunks",
            0
        )
    )

    decoded = receiver.get(
        "windows_decoded",
        0
    )

    progress = min(
        decoded / total_windows,
        1.0
    )

    st.progress(progress)

    sha = receiver.get(
        "sha256_match"
    )

    if sha is True:
        st.success(
            "SHA256 Verified"
        )

    elif sha is False:
        st.error(
            "SHA256 Failed"
        )

    storage = receiver.get(
        "storage_path"
    )

    if storage:
        st.code(storage)

st.divider()

# ---------------------------------------------------------
# HISTORY
# ---------------------------------------------------------

st.subheader("Transfer Information")

left, right = st.columns(2)

with left:

    st.write(
        f"Transfer ID: {transfer_id}"
    )

    st.write(
        f"Classification: {state.get('criticality','standard')}"
    )

    st.write(
        f"Compression: {state.get('compression_algorithm','none')}"
    )

with right:

    st.write(
        f"Windows: {state.get('total_windows',0)}"
    )

    st.write(
        f"Overall State: {overall_state}"
    )

# ---------------------------------------------------------
# WARNINGS
# ---------------------------------------------------------

warnings = state.get(
    "warnings",
    []
)

if warnings:

    with st.expander(
        f"Warnings ({len(warnings)})"
    ):
        for w in warnings:
            st.warning(w)

# ---------------------------------------------------------
# ERRORS
# ---------------------------------------------------------

errors = state.get(
    "errors",
    []
)

if errors:

    with st.expander(
        f"Errors ({len(errors)})",
        expanded=True
    ):
        for e in errors:
            st.error(e)

# ---------------------------------------------------------
# AUTO REFRESH
# ---------------------------------------------------------

st.caption(
    "Auto-refreshing every 1 second"
)