import sys
from pathlib import Path
import os
import json
import time
import streamlit as st

# Add project root to sys.path so 'common' module can be found
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from common import state_writer

# Absolute path for the state file
STATE_FILE = str(root_dir / "demo_output" / "transfer_state.json")

# Page Config
st.set_page_config(
    page_title="Data Diode Monitor",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="expanded",
)

def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

def state_badge(state):
    colors = {
        "IDLE": "#808080",      # Grey
        "RECEIVING": "#0000FF", # Blue
        "DECODING": "#FFA500",  # Orange
        "ENCODING_RS": "#00CED1", # DarkCyan
        "SENDING": "#0000FF",   # Blue
        "VERIFYING": "#CCCC00", # Darker Yellow
        "ACCEPTED": "#008000",  # Green
        "FAILED": "#FF0000"     # Red
    }
    color = colors.get(state, "#808080")
    return f'<span style="background-color:{color}; color:white; padding:4px 8px; border-radius:4px; font-weight:bold;">{state}</span>'

# Header
st.title("Data Diode Monitor")

state = load_state()

if not state or state.get("overall_state") == "IDLE":
    st.markdown("### Waiting for transfer to begin...")
    
    # DIAGNOSTICS (only in IDLE/Missing state)
    with st.expander("System Diagnostics"):
        st.write(f"**Current Working Directory:** `{os.getcwd()}`")
        st.write(f"**State File Path:** `{STATE_FILE}`")
        st.write(f"**File Exists:** `{os.path.exists(STATE_FILE)}`")
        if os.path.exists(STATE_FILE):
            st.write("**File Content Snippet:**")
            try:
                with open(STATE_FILE, 'r') as f:
                    st.code(f.read()[:500])
            except Exception as e:
                st.error(f"Error reading file: {e}")

    # Sidebar
    with st.sidebar:
        st.title("Controls")
        if st.button("Clear State"):
            state_writer.clear_state()
            st.rerun()
        st.divider()
        st.info("Strictly one-way file transfer. The receiver process NEVER sends data back to the sender.")
        st.caption("Protocol v1.0.0")
else:
    # Top bar info
    transfer_id = state.get("transfer_id", "—")
    file_name = state.get("file_name", "—")
    overall_state = state.get("overall_state", "IDLE")
    last_updated = state.get("last_updated", 0)
    updated_ago = int(time.time() - last_updated)

    st.markdown(
        f"**ID:** `{transfer_id[:8]}` | **File:** `{file_name}` | {state_badge(overall_state)} "
        f"&nbsp;&nbsp;&nbsp; <small>Updated {updated_ago}s ago</small>",
        unsafe_allow_html=True
    )
    st.divider()

    col_send, col_recv = st.columns(2)

    # Sender Column
    with col_send:
        st.header("Sender")
        s = state.get("sender", {})
        status = s.get("status", "idle").upper()
        st.markdown(f"Status: {state_badge(status)}", unsafe_allow_html=True)
        
        m1, m2 = st.columns(2)
        m3, m4 = st.columns(2)
        
        orig_size = state.get("original_size_mb", 0)
        comp_size = s.get("compressed_size_mb", 0)
        ratio = s.get("compression_ratio", 1.0)
        
        m1.metric("Original Size", f"{orig_size:.1f} MB")
        m2.metric("Compressed Size", f"{comp_size:.1f} MB", delta=f"{ratio:.1f}x")
        m3.metric("Packets Sent", f"{s.get('total_packets_sent', 0):,}")
        m4.metric("Data Transmitted", f"{s.get('bytes_transmitted_mb', 0):.1f} MB")
        
        total_win = state.get("total_windows", 1)
        sent_win = s.get("windows_sent", 0)
        progress = min(max(sent_win / (total_win or 1), 0.0), 1.0)
        st.progress(progress)
        
        st.write(f"Windows: **{sent_win} / {total_win}** | Elapsed: **{s.get('elapsed_s', 0):.1f}s** | ETA: **{s.get('eta_str', '—')}**")
        st.caption(f"Algo: {state.get('compression_algorithm', 'none')} | Criticality: {state.get('criticality', 'standard')}")

    # Receiver Column
    with col_recv:
        st.header("Receiver")
        r = state.get("receiver", {})
        status = r.get("status", "idle").upper()
        st.markdown(f"Status: {state_badge(status)}", unsafe_allow_html=True)

        m1, m2 = st.columns(2)
        m3, m4 = st.columns(2)
        
        total_win = state.get("total_windows", 1)
        decoded_win = r.get("windows_decoded", 0)
        
        m1.metric("Packets Received", f"{r.get('total_packets_rx', 0):,}")
        m2.metric("Windows Decoded", f"{decoded_win} / {total_win}")
        m3.metric("Fountain Recovered", f"{r.get('fountain_recovered_chunks', 0):,}")
        rs_rec = r.get("rs_recovered_chunks", 0)
        m4.metric("RS Recovered", f"{rs_rec:,}", delta=f"{rs_rec}" if rs_rec > 0 else None, delta_color="inverse")

        progress = min(max(decoded_win / (total_win or 1), 0.0), 1.0)
        st.progress(progress)
        st.write(f"Windows: **{decoded_win} / {total_win}** | Elapsed: **{r.get('elapsed_s', 0):.1f}s**")

        sha_match = r.get("sha256_match")
        if sha_match is True:
            st.success("✅ SHA-256 Verified")
        elif sha_match is False:
            st.error("❌ SHA-256 FAILED")
        
        storage_path = r.get("storage_path")
        if storage_path:
            st.write("Storage Path:")
            st.code(storage_path)

    # Bottom Section: Errors and Warnings
    errors = state.get("errors", [])
    warnings = state.get("warnings", [])

    if errors:
        with st.expander(f"Errors ({len(errors)})", expanded=True):
            for err in errors:
                st.error(err)

    if warnings:
        with st.expander(f"Warnings ({len(warnings)})", expanded=False):
            for warn in warnings:
                st.warning(warn)

    # Sidebar
    with st.sidebar:
        st.title("Controls")
        if st.button("Clear State"):
            state_writer.clear_state()
            st.rerun()
        st.divider()
        st.info("Strictly one-way file transfer. The receiver process NEVER sends data back to the sender.")
        st.caption("Protocol v1.0.0")

# Auto-refresh
try:
    time.sleep(1)
    st.rerun()
except Exception:
    pass
