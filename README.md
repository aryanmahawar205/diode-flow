# DiodeFlow

High-assurance one-way data transfer framework for secure environments using fountain codes, Reed-Solomon recovery, Merkle-tree verification, and hardware data diode integration.

---

# Overview

DiodeFlow is a secure, loss-resilient, one-way file transfer framework designed for deployment across hardware-enforced data diodes.

The project is built for environments where:

- bidirectional communication is prohibited,
- retransmission is impossible,
- data integrity is critical,
- and transfer reliability must be maintained despite packet loss.

Traditional transfer protocols such as TCP are fundamentally incompatible with physical one-way links because they rely on acknowledgements and retransmissions.

DiodeFlow addresses this by combining:

- Fountain Codes (LT / future RaptorQ),
- Reed-Solomon forward error correction,
- multi-pass probabilistic transmission,
- interleaving,
- Merkle-tree chunk verification,
- cryptographic authentication,
- and bounded receiver-side validation.

The result is a modular transport pipeline capable of secure and resilient transfer over physically enforced one-way communication channels.

---

# Key Features

## One-Way Communication Architecture

Designed specifically for hardware data diode environments.

- No acknowledgements
- No retransmissions
- No reverse channel dependency
- Receiver never transmits

---

## Fountain Code Based Recovery

Uses LT fountain codes (with future RaptorQ abstraction support) to recover from packet loss without retransmission.

### Features

- Probabilistic recovery
- Rateless encoding
- Configurable redundancy overhead
- Multi-pass transmission with independent seeds

---

## Reed-Solomon Chunk Recovery

Adds deterministic chunk-level recovery on top of probabilistic fountain recovery.

### Protects Against

- Unrecoverable chunk gaps
- Burst-loss edge cases
- Partial decode failures

---

## Multi-Pass Transmission

Each transmission pass generates different encoded packets using independent seeds.

### Benefits

- Resilience against correlated loss
- Improved decode probability
- Robust burst-loss recovery

---

## Packet Interleaving

Transmission order is intentionally shuffled to distribute burst packet loss across logical chunk space.

This significantly improves decode stability under real network conditions.

---

## Merkle Tree Integrity Verification

Per-chunk cryptographic verification using Merkle trees.

### Enables

- Chunk-level integrity validation
- Corruption localization
- Hierarchical verification
- Scalable integrity checks for large files

---

## End-to-End SHA-256 Verification

Final reconstructed file is verified against the original SHA-256 digest.

### Ensures

- Byte-perfect reconstruction
- Final transfer integrity assurance

---

## Authenticated Metadata

Supports:

- Ed25519 manifest signatures
- BLAKE3 packet authentication
- Replay protection
- Trusted sender verification

---

## Sliding Window Architecture

Large files are divided into independently decodable windows.

### Benefits

- Bounded memory usage
- Scalable Tanner graph sizes
- Lower decode latency
- Production-scale transfer support

---

## Defensive Receiver Design

Receiver architecture is intentionally strict and bounded.

### Includes

- Decoder hard limits
- Bounded memory pools
- Schema validation
- Replay protection
- Malformed packet rejection
- Resource exhaustion mitigation

---

# High-Level Architecture

```text
SENDER PIPELINE
═══════════════════════════════════════

[M0]  Transfer Manifest Generator
[M1]  File Windowing Engine
[M2]  File Analyzer & Chunker
[M3]  Merkle Tree Builder
[M4]  Reed-Solomon Encoder
[M5]  Transfer Profile Selector
[M6]  Fountain Encoder
[M7]  Multi-Pass Generator
[M8]  Packet Interleaver
[M9]  Metadata + Auth Tag Generator
[M10] Protocol Buffer Serializer
[M11] Rate-Controlled UDP Transmitter

                ↓
      [ Physical Data Diode ]
                ↓

RECEIVER PIPELINE
═══════════════════════════════════════

[M12] UDP Receiver & Packet Buffer
[M13] Packet Validator
[M14] Authentication Verifier
[M15] Multi-Pass Packet Pooler
[M16] Fountain Decoder
[M17] Reed-Solomon Decoder
[M18] Merkle Chunk Verifier
[M19] Window Reassembler
[M20] File Reassembler
[M21] SHA-256 + Merkle Root Verifier
[M22] Quarantine Pipeline
[M23] Secure Storage
```

---

# Why Fountain Codes?

In a one-way system:

- Retransmission is impossible
- Acknowledgements cannot exist
- Packet loss must be tolerated proactively

Fountain codes solve this by allowing the receiver to reconstruct the original data from any sufficiently large subset of encoded packets.

DiodeFlow currently implements:

- LT Codes

### Planned

- RaptorQ support through abstraction interfaces

---

# Why Reed-Solomon + Fountain Codes?

The two mechanisms protect different failure layers.

| Mechanism | Protects Against |
|---|---|
| Fountain Codes | Packet-level stochastic loss |
| Reed-Solomon | Chunk-level deterministic recovery |

Layering both improves robustness significantly under real-world loss conditions.

---

# Why Merkle Trees?

A single end-to-end hash is insufficient for large-scale secure transfers.

Merkle trees enable:

- Chunk-level verification
- Corruption localization
- Hierarchical validation
- Scalable integrity checking

This allows corrupt chunks to be identified precisely instead of rejecting entire transfers blindly.

---

# Trust Model

DiodeFlow explicitly separates trust boundaries.

| Stage | Trust Level |
|---|---|
| Source network | Untrusted |
| Post-diode UDP input | Untrusted |
| Post-packet validation | Structurally trusted |
| Post-authentication | Authenticated |
| Post-Merkle verification | Integrity trusted |
| Post-quarantine | Policy trusted |
| Secure storage | Fully trusted |

---

# Security Design Goals

- No reverse communication
- Strong integrity guarantees
- Sender authentication
- Replay protection
- Resource exhaustion resistance
- Malformed packet rejection
- Bounded decoder behavior
- Cryptographic verification
- Deterministic trust transitions

---

# Planned Development Phases

## Phase 1 — Core Transport

- Chunking
- LT encode/decode
- UDP transport
- Merkle verification
- SHA validation

## Phase 2 — Robustness

- Windowing
- Reed-Solomon
- Multi-pass encoding
- Interleaving
- Loss simulation

## Phase 3 — Security Hardening

- Ed25519 authentication
- BLAKE3 packet MACs
- Decoder hard limits
- Quarantine state machine

## Phase 4 — Optimization

- RaptorQ integration
- Performance tuning
- Hardware diode deployment

---

# Project Status

## Current Status

- Architecture finalized
- Software implementation in progress

## Planned

- Loopback software simulation
- Loss-injection testing
- Hardware diode integration
- Real-world throughput evaluation

---

# Technology Stack

- Python
- Protocol Buffers
- UDP
- Reed-Solomon FEC
- LT Fountain Codes
- SHA-256
- Merkle Trees
- Ed25519
- BLAKE3

---

# Repository Structure

```text
data_diode/
├── common/
├── fountain/
├── sender/
├── receiver/
├── tests/
├── simulate_diode.py
└── README.md
```

---

# Disclaimer

This project is intended for research, defensive security engineering, and secure systems experimentation.

It is not intended for offensive security usage.

---

# Future Work

- RaptorQ integration
- FPGA acceleration
- Zero-copy packet pipeline
- High-throughput NIC tuning
- Multi-diode clustering
- Secure audit journaling
- Adaptive redundancy tuning
- Real-time telemetry dashboards

---

# License

MIT License

---
