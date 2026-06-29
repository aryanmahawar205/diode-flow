# DiodeFlow

> High-Assurance One-Way Data Transfer Framework for Air-Gapped and Hardware Data Diode Environments

DiodeFlow is a secure, reliable, and modular one-way file transfer framework designed for deployment across hardware-enforced data diodes and isolated (air-gapped) environments.

Unlike traditional transfer protocols such as TCP, DiodeFlow operates without acknowledgements, retransmissions, or any reverse communication channel. Reliability is instead achieved through a combination of LT Fountain Codes, Reed–Solomon Forward Error Correction, multi-pass transmission, packet interleaving, cryptographic authentication, and layered integrity verification.

The project supports both software simulation and deployment across two physically isolated systems connected through a hardware data diode.

---

# Key Features

## One-Way Communication

- No acknowledgements
- No retransmissions
- No reverse communication
- Compatible with hardware-enforced data diodes

---

## Reliability

- LT Fountain Code based recovery
- Reed–Solomon Forward Error Correction
- Multi-pass packet transmission
- Packet interleaving
- Adaptive transfer profiles
- Sliding window architecture
- Packet loss simulation

---

## Security

- Ed25519 manifest signatures
- BLAKE3 packet authentication
- SHA-256 compressed file verification
- SHA-256 original file verification
- Merkle tree integrity verification
- Defensive packet validation
- Replay protection
- Secure quarantine pipeline

---

## Performance

- Streaming architecture
- Window-based processing
- Bounded memory usage
- Large file support
- Configurable packet rate
- Offline deployment support

---

## Monitoring

Real-time Streamlit dashboard displaying:

- Transfer progress
- Sender statistics
- Receiver statistics
- ETA
- Packet counts
- Recovery statistics
- Security verification status
- Event timeline
- Warnings and errors

---

# System Architecture

```
                    SENDER

          File
            │
            ▼
      LZ4 Compression
            │
            ▼
      Window Generation
            │
            ▼
        Chunking
            │
            ▼
      Merkle Generation
            │
            ▼
   Reed-Solomon Encoding
            │
            ▼
     LT Fountain Encoding
            │
            ▼
    Multi-Pass Generation
            │
            ▼
      Packet Interleaving
            │
            ▼
    BLAKE3 Authentication
            │
            ▼
      UDP Transmission
══════════════════════════════════════════
        HARDWARE DATA DIODE
══════════════════════════════════════════
      UDP Reception
            │
            ▼
      Packet Validation
            │
            ▼
     BLAKE3 Verification
            │
            ▼
   Manifest Authentication
            │
            ▼
    LT Fountain Decoding
            │
            ▼
  Reed-Solomon Recovery
            │
            ▼
      Window Assembly
            │
            ▼
       File Assembly
            │
            ▼
 SHA-256 Verification
            │
            ▼
      Decompression
            │
            ▼
 Final SHA-256 Verification
            │
            ▼
    Quarantine Pipeline
            │
            ▼
      Secure Storage
```

---

# Current Features

✔ LT Fountain Codes

✔ Reed–Solomon Recovery

✔ Adaptive Windowing

✔ Adaptive Chunking

✔ Adaptive Transfer Profiles

✔ Multi-Pass Transmission

✔ Packet Interleaving

✔ LZ4 Compression

✔ Ed25519 Manifest Authentication

✔ BLAKE3 Packet Authentication

✔ SHA-256 File Verification

✔ Merkle Tree Generation

✔ Streaming File Assembly

✔ Secure Quarantine Pipeline

✔ Streamlit Monitoring Dashboard

✔ Offline Installation

✔ Air-Gapped Deployment

✔ Hardware Data Diode Support

✔ Packet Loss Simulation

✔ Two-System Deployment

---

# Repository Structure

```text
diode-flow/

├── common/                  # Shared utilities, configuration and security
├── fountain/                # LT Fountain encoder/decoder
├── sender/                  # Sender pipeline modules
├── receiver/                # Receiver pipeline modules
├── ui/                      # Streamlit monitoring dashboard
├── keys/                    # Ed25519 key pairs
├── tests/                   # Test suite
├── test_files/              # Sample transfer files

├── wheelhouse/              # Offline Python packages

├── sender_node.py           # Sender executable (two-PC deployment)
├── receiver_node.py         # Receiver executable (two-PC deployment)
├── run_demo.py              # Local sender + receiver simulation

├── install_offline.sh
├── start_sender.sh
├── start_receiver.sh
├── start_ui.sh

├── requirements.txt
├── README.md
└── LICENSE
```

# Installation

## Prerequisites

DiodeFlow has been tested on Linux systems and is intended for deployment in isolated or air-gapped environments.

### Requirements

- Python 3.10 or later
- Linux (Ubuntu recommended)
- Network interface supporting UDP communication
- (Optional) Hardware data diode setup
- (Optional) Streamlit for monitoring dashboard

---

## Online Installation

Clone the repository and install dependencies:

```bash
git clone <repository-url>

cd diode-flow

pip install -r requirements.txt
```

---

## Offline Installation

DiodeFlow includes a complete offline deployment package.

The repository contains:

- Pre-built Python wheels
- Offline installation scripts
- Local virtual environment setup

No internet connection is required.

Run:

```bash
chmod +x *.sh

./install_offline.sh
```

The installer automatically:

- Creates a local virtual environment
- Installs all dependencies from the bundled `wheelhouse/`
- Does not access PyPI
- Is suitable for isolated and air-gapped systems

---

# Deployment Modes

DiodeFlow supports three deployment modes.

## 1. Local Simulation

Runs both sender and receiver on the same machine.

Useful for:

- Development
- Testing
- Packet loss simulation
- Performance evaluation

Run:

```bash
python run_demo.py \
    --file test_files/100MB.txt
```

---

## 2. Two-System Deployment

Runs sender and receiver on separate systems connected over Ethernet.

### Receiver

```bash
python receiver_node.py
```

### Sender

```bash
python sender_node.py \
    --file test_files/100MB.txt \
    --receiver-ip 192.168.1.20 \
    --security standard
```

This deployment mirrors the architecture used during real hardware testing while operating over a normal Ethernet connection.

---

## 3. Hardware Data Diode Deployment

DiodeFlow is designed to operate across physically enforced one-way communication channels.

Typical deployment consists of:

```
Sender PC
      │
      │ Ethernet
      │
Media Converter
      │
      │ Optical Fiber
      ▼
Hardware Data Diode
      │
      │ Optical Fiber
      ▼
Media Converter
      │
      │ Ethernet
      ▼
Receiver PC
```

Since ARP broadcasts cannot traverse a one-way link, the sender supports automatic installation of a static IP-to-MAC neighbour entry before transmission.

Example:

```bash
sudo python sender_node.py \
    --file test_files/100MB.txt \
    --receiver-ip 192.168.1.20 \
    --receiver-mac AA:BB:CC:DD:EE:FF \
    --interface enp3s0
```

The sender automatically configures the required neighbour mapping before the transfer begins, eliminating the need for manual ARP configuration.

---

# Running the Monitoring Dashboard

Launch the Streamlit dashboard:

```bash
./start_ui.sh
```

or

```bash
streamlit run ui/streamlit_app.py
```

The dashboard displays live information throughout the transfer, including sender activity, receiver progress, throughput, integrity verification, recovery statistics, and security status.

---

# Command Line Options

## Local Demo

```bash
python run_demo.py \
    --file test_files/sample.bin \
    --security classified \
    --pps 50000 \
    --loss 0.10
```

### Parameters

| Parameter | Description |
|------------|-------------|
| `--file` | File to transfer |
| `--security` | standard / critical / classified |
| `--pps` | Packets transmitted per second |
| `--loss` | Simulated packet loss (0.0–1.0) |
| `--port` | UDP port |
| `--timeout` | Transfer timeout |

---

## Sender Node

```bash
python sender_node.py \
    --file test_files/sample.bin \
    --receiver-ip 192.168.1.20 \
    --receiver-mac AA:BB:CC:DD:EE:FF \
    --interface enp3s0 \
    --security critical
```

### Additional Parameters

| Parameter | Description |
|------------|-------------|
| `--receiver-ip` | Receiver IP address |
| `--receiver-mac` | Receiver MAC address |
| `--interface` | Sender network interface |

---

## Receiver Node

Simply run:

```bash
python receiver_node.py
```

The receiver continuously listens for incoming transfers until interrupted.

---

# Security Profiles

DiodeFlow supports multiple transfer profiles that adjust redundancy and reliability parameters according to the desired level of protection.

| Profile | Purpose |
|----------|---------|
| **Standard** | Normal operation with balanced throughput and redundancy |
| **Critical** | Increased redundancy and stronger recovery for important transfers |
| **Classified** | Maximum redundancy and reliability for highly sensitive environments |

Each profile automatically tunes multiple internal parameters, including:

- Reed–Solomon parity
- Fountain code overhead
- Multi-pass count
- Interleaving depth
- Window configuration

This allows the system to balance bandwidth efficiency against recovery probability without requiring manual tuning.

# Monitoring Dashboard

DiodeFlow includes a real-time Streamlit monitoring dashboard that provides operational visibility throughout the transfer lifecycle.

## Transfer Information

* Transfer ID
* File Name
* Security Classification
* Compression Status
* Current Transfer State

## Sender Metrics

* Original File Size
* Compressed File Size
* Packets Generated
* Packets Sent
* Current Window
* Current Pass
* Transfer Rate
* Estimated Time Remaining

## Receiver Metrics

* Packets Received
* Windows Decoded
* Fountain Decode Progress
* Reed–Solomon Recovery Statistics
* File Reconstruction Progress
* Output Storage Location

## Security Monitoring

* Ed25519 Manifest Verification
* BLAKE3 Packet Authentication
* SHA-256 Integrity Verification
* Security Warnings
* Error Events
* Transfer Status

---

# Technology Stack

| Component              | Technology        |
| ---------------------- | ----------------- |
| Language               | Python            |
| Transport Protocol     | UDP               |
| Compression            | LZ4               |
| Fountain Coding        | LT Fountain Codes |
| Error Correction       | Reed–Solomon      |
| Packet Authentication  | BLAKE3            |
| Digital Signatures     | Ed25519           |
| Integrity Verification | SHA-256           |
| Monitoring             | Streamlit         |

---

# Quick Start (Hardware Deployment)

DiodeFlow is primarily designed for deployment on **two independent systems** connected through a hardware data diode or a one-way network link.

### Step 1 — Start the Receiver

```bash
python receiver_node.py
```

The receiver waits for incoming transfers.

---

### Step 2 — Launch the Monitoring Dashboard (Optional)

```bash
./start_ui.sh
```

or

```bash
streamlit run ui/streamlit_app.py
```

---

### Step 3 — Start the Sender

```bash
sudo python sender_node.py \
    --file test_files/100MB.txt \
    --receiver-ip <receiver-ip> \
    --receiver-mac <receiver-mac> \
    --interface <sender-network-interface> \
    --security classified
```

The sender automatically configures the required IP-to-MAC neighbour mapping before transmission, allowing operation across hardware data diode deployments without manual ARP configuration.

---

# Local Simulation

For development and testing, DiodeFlow also provides a local simulation mode where both sender and receiver execute on the same machine.

```bash
python run_demo.py \
    --file test_files/100MB.txt
```

Packet loss can be simulated using:

```bash
python run_demo.py \
    --file test_files/100MB.txt \
    --loss 0.15
```

This mode is intended for development, debugging, and performance evaluation.

---

# Project Status

## Current Status

**Functional Prototype**

### Implemented

* One-way UDP transport
* Sliding window architecture
* Adaptive chunking
* LT Fountain encoding and decoding
* Reed–Solomon Forward Error Correction
* Multi-pass transmission
* Packet interleaving
* LZ4 compression
* Ed25519 manifest authentication
* BLAKE3 packet authentication
* SHA-256 integrity verification
* Merkle tree generation
* Secure quarantine pipeline
* Streaming file reconstruction
* Real-time monitoring dashboard
* Offline dependency packaging
* Air-gapped deployment support
* Hardware data diode compatibility

---

# Future Enhancements

* RaptorQ fountain code integration
* Adaptive redundancy tuning
* FPGA acceleration
* Zero-copy packet pipeline
* Multi-channel transfer support
* Throughput optimization
* Advanced telemetry and analytics

---

# Disclaimer

DiodeFlow is intended for:

* Research
* Secure Systems Engineering
* Air-Gapped Infrastructure
* Defensive Cybersecurity
* Hardware Data Diode Deployments

This project is intended solely for defensive security and secure systems research.

---

# License

Distributed under the MIT License.

See the `LICENSE` file for additional information.
