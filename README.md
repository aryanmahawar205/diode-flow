# DiodeFlow

High-Assurance One-Way Data Transfer Framework for Air-Gapped and Secure Environments

---

# Overview

DiodeFlow is a secure, loss-resilient, one-way file transfer framework designed for deployment across hardware-enforced data diodes and air-gapped systems.

The system enables reliable transfer of files from a lower-trust network to a higher-trust network without requiring acknowledgements, retransmissions, or any reverse communication path.

Unlike traditional protocols such as TCP, DiodeFlow is specifically designed for environments where:

* Bidirectional communication is prohibited
* Retransmission is impossible
* Packet loss must be tolerated proactively
* Data integrity is mandatory
* Sender authentication is required

DiodeFlow combines fountain coding, Reed-Solomon forward error correction, cryptographic authentication, integrity verification, and secure receiver-side validation into a single modular transfer pipeline.

---

# Key Features

## One-Way Transfer Architecture

Designed specifically for physical data diode deployments.

### Guarantees

* No acknowledgements
* No retransmissions
* No receiver-to-sender communication
* Strict one-way data flow

---

## Fountain Code Recovery

DiodeFlow uses LT Fountain Codes to provide probabilistic packet-loss recovery.

### Benefits

* Rateless encoding
* Loss tolerance without retransmission
* Recovery from arbitrary packet loss
* Scalable redundancy control

---

## Reed-Solomon Forward Error Correction

Additional deterministic protection layer on top of fountain coding.

### Protects Against

* Missing chunks
* Decode edge cases
* Burst packet loss
* Partial recovery failures

---

## Multi-Pass Transmission

Each pass generates independent encoded packets.

### Benefits

* Increased recovery probability
* Better resilience against correlated loss
* Improved burst-loss performance

---

## Packet Interleaving

Packets are intentionally reordered before transmission.

### Benefits

* Burst-loss mitigation
* Improved decoder stability
* Better packet distribution

---

## Sliding Window Architecture

Large files are divided into independently decodable windows.

### Benefits

* Bounded memory usage
* Scalable transfers
* Lower decode latency
* Large-file support

---

## Merkle Tree Integrity Verification

Each window includes cryptographic integrity verification.

### Enables

* Chunk-level verification
* Corruption detection
* Hierarchical integrity validation
* Scalable verification of large files

---

## End-to-End SHA-256 Validation

Two levels of verification are performed:

### Compressed File Verification

Verifies the transmitted compressed payload.

### Original File Verification

Verifies the reconstructed file after decompression.

This guarantees byte-perfect reconstruction.

---

## Ed25519 Manifest Authentication

Transfer manifests are digitally signed.

### Benefits

* Sender authentication
* Tamper detection
* Trusted origin verification

---

## BLAKE3 Packet Authentication

Every packet includes an authentication tag.

### Benefits

* Packet tampering detection
* Early packet rejection
* Fast verification

---

## Secure Receiver Pipeline

Receiver architecture is intentionally defensive.

### Includes

* Packet validation
* Replay protection
* Cryptographic verification
* Integrity verification
* Quarantine staging
* Secure storage acceptance

---

## Real-Time Monitoring Dashboard

Streamlit-based monitoring interface.

### Displays

* Transfer progress
* Sender status
* Receiver status
* Packet counts
* Recovery statistics
* ETA estimation
* SHA verification results
* Security status
* Warnings and errors

---

# Security Model

DiodeFlow performs verification in stages.

| Stage                 | Trust Level          |
| --------------------- | -------------------- |
| Incoming UDP Traffic  | Untrusted            |
| Packet Validation     | Structurally Trusted |
| BLAKE3 Verification   | Authenticated        |
| Manifest Verification | Sender Trusted       |
| Merkle Verification   | Integrity Trusted    |
| SHA-256 Verification  | File Trusted         |
| Secure Storage        | Accepted             |

---

# Transfer Pipeline

## Sender Pipeline

```text
File
 │
 ▼
Compression
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
```

## Receiver Pipeline

```text
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
Fountain Decoding
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
Secure Storage
```

---

# Current Implemented Features

## Complete

* LT Fountain Codes
* Reed-Solomon Recovery
* Multi-Pass Transmission
* Packet Interleaving
* Sliding Windows
* Merkle Trees
* SHA-256 Verification
* Ed25519 Signatures
* BLAKE3 Packet MACs
* Compression Pipeline
* Real-Time Monitoring UI
* Offline Deployment Support
* Air-Gapped Operation
* Packet Loss Simulation
* Quarantine Storage
* Secure Acceptance Pipeline

---

# Technology Stack

* Python 3.11+
* UDP
* LT Fountain Codes
* Reed-Solomon
* SHA-256
* Merkle Trees
* Ed25519
* BLAKE3
* LZ4 Compression
* Streamlit

---

# Repository Structure

```text
diode-flow/
│
├── common/
├── fountain/
├── sender/
├── receiver/
├── ui/
├── keys/
├── tests/
├── test_files/
│
├── wheelhouse/
│
├── run_demo.py
├── requirements.txt
│
├── install_offline.sh
├── start_sender.sh
├── start_ui.sh
│
├── README.md
└── LICENSE
```

---

# Installation

## Online Development Installation

```bash
pip install -r requirements.txt
```

---

# Offline Installation

Designed for isolated and air-gapped environments.

### Install

```bash
chmod +x *.sh

./install_offline.sh
```

This creates a local virtual environment and installs all dependencies directly from the bundled wheelhouse.

No internet connection is required.

---

# Running the System

## Launch Monitoring Dashboard

```bash
./start_ui.sh
```

or

```bash
streamlit run ui/streamlit_app.py
```

---

## Transfer a File

```bash
python run_demo.py \
--file test_files/sample.bin
```

---

## Additional Options

```bash
python run_demo.py \
--file test_files/sample.bin \
--security classified \
--pps 50000 \
--loss 0.10
```

### Parameters

| Parameter  | Description                      |
| ---------- | -------------------------------- |
| --file     | File to transfer                 |
| --security | standard / critical / classified |
| --pps      | Packets per second               |
| --loss     | Simulated packet loss            |
| --port     | UDP port                         |
| --timeout  | Transfer timeout                 |

---

# User Interface

The monitoring dashboard provides:

### Transfer Information

* Transfer ID
* File Name
* Classification
* Compression Algorithm

### Sender Metrics

* Original Size
* Compressed Size
* Packets Sent
* Data Sent
* ETA
* Window Progress

### Receiver Metrics

* Packets Received
* Windows Decoded
* Fountain Recovery
* Reed-Solomon Recovery
* Storage Location

### Security Dashboard

* Ed25519 Verification
* BLAKE3 Authentication Status
* Compressed SHA-256 Validation
* Original SHA-256 Validation

### Operational Status

* Active State
* Warnings
* Errors
* Event Timeline

---

# Deployment on Air-Gapped Systems

## Requirements

* Python 3.11+
* Local copy of repository
* No internet connection required

## Deployment Steps

### Step 1

Copy the entire repository to both systems.

### Step 2

Run:

```bash
./install_offline.sh
```

### Step 3

Launch UI:

```bash
./start_ui.sh
```

### Step 4

Start transfers through either:

* CLI
* Monitoring UI

---

# Testing

Run:

```bash
python run_demo.py --file test_files/100MB.txt
```

Example loss simulation:

```bash
python run_demo.py \
--file test_files/100MB.txt \
--loss 0.15
```

---

# Current Status

## Status

Production-ready prototype

### Implemented

* Secure one-way transfer
* Cryptographic verification
* Error correction
* Monitoring dashboard
* Offline deployment

### Future Enhancements

* RaptorQ support
* Performance optimization
* Hardware data diode integration
* FPGA acceleration
* Advanced telemetry

---

# Disclaimer

This project is intended for:

* Research
* Defensive Security Engineering
* Secure Systems Development
* Air-Gapped Data Transfer Experiments

It is not intended for offensive security activities.

---

# License

MIT License
