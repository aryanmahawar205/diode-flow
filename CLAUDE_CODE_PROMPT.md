## WHAT YOU ARE BUILDING

A **software-only Data Diode system** implemented in Python.

A data diode enforces **strictly one-way communication** — data flows from
sender to receiver, and absolutely nothing flows back. This is a core security
primitive used in critical infrastructure, defense, and classified environments
to guarantee that a secure network cannot be exfiltrated through the transfer
channel.

The system must be **production-grade in design**: not a prototype. Every
module must be individually testable, well-documented, and built with explicit
reasoning behind every design choice.

**Phase scope:** Software only. No hardware integration yet. The physical data
diode is simulated as two separate Python processes communicating over UDP
loopback (127.0.0.1). The one-way constraint is enforced at the application
level — the receiver process never opens an outbound socket under any
circumstances.

**Language:** Python 3.11+
**Environment:** GitHub Codespaces (Ubuntu, standard container)
**Testing:** pytest, module-by-module, with edge case coverage

---

## WHY THIS ARCHITECTURE EXISTS — CORE REASONING

Before the modules, understand the fundamental problems this system solves.
These problems drive every design decision:

### Problem 1: UDP is unreliable, but retransmission is impossible
Normal reliable protocols (TCP) recover from loss by asking the sender to
resend. In a data diode, the receiver cannot send anything back — ever.
Therefore all loss recovery must be handled **proactively by the sender**
before packets cross the diode.

### Problem 2: Large files create large Tanner graphs
A 10 GB file at 1200-byte chunks = ~8.7 million chunks. Building a single
decode graph for 8.7 million nodes exhausts memory and CPU. The system must
process files in bounded-memory **windows** so it scales to any file size.

### Problem 3: Packet corruption is not the same as packet loss
Fountain codes (the core recovery mechanism) handle **loss** — missing packets.
They do NOT handle **corruption** — packets that arrive but contain wrong data.
CRC32 alone has a collision probability and is not adversarially secure.
Therefore integrity is layered: CRC32C (fast, catches accidents) + BLAKE3-MAC
(cryptographic, catches tampering) + Merkle tree (per-chunk cryptographic
proof) + SHA-256 (end-to-end file integrity).

### Problem 4: Authenticity vs Integrity are different guarantees
SHA-256 and Merkle proofs answer: "was the data changed?"
Ed25519 signatures answer: "did this come from a trusted sender?"
In a diode system there is no handshake or authentication channel — a
malicious actor on the source-side network could inject forged UDP packets.
Ed25519 over the transfer manifest + Merkle root closes this gap.

### Problem 5: The decoder is a DoS attack surface
A fountain decoder builds a bipartite graph in memory. Malformed packets
claiming extreme degrees or impossible K values can cause graph explosion and
memory exhaustion. Hard limits must be enforced at the validation layer before
any packet touches the decoder.

### Problem 6: Burst loss is qualitatively different from random loss
Random loss at 10% is handled easily by fountain code overhead. But a 10-second
network hiccup wiping 500 consecutive packets overwhelms single-pass overhead.
Multi-pass transmission with different encoding seeds, combined with packet
interleaving, ensures burst loss hits different parts of the logical packet
space in each pass — the combined pool covers what any single pass cannot.

---

## COMPLETE FILE STRUCTURE

Build exactly this structure. Do not deviate from module file names — they map
directly to the module numbering used throughout this document.

```
data_diode/
│
├── common/
│   ├── __init__.py
│   ├── config.py              # global constants, profile tables, defaults
│   ├── models.py              # shared dataclasses used across sender+receiver
│   └── proto/
│       ├── manifest.proto     # Transfer manifest Protobuf schema
│       ├── packet.proto       # Encoded packet Protobuf schema
│       └── generated/         # Output of protoc compilation
│           ├── __init__.py
│           ├── manifest_pb2.py
│           └── packet_pb2.py
│
├── fountain/                  # Completely standalone — no imports from sender/receiver
│   ├── __init__.py            # Auto-registers all implementations
│   ├── interface.py           # IFountainEncoder, IFountainDecoder ABCs + registry
│   ├── lt_encoder.py          # LT encoder — Robust Soliton Distribution
│   ├── lt_decoder.py          # LT decoder — belief propagation peeling
│   └── raptorq_stub.py        # RaptorQ stub — NotImplementedError, registered
│
├── sender/
│   ├── __init__.py
│   ├── m0_manifest.py         # Transfer Manifest Generator
│   ├── m1_windowing.py        # File Windowing Engine
│   ├── m2_chunker.py          # File Analyzer & Chunker
│   ├── m3_merkle.py           # Merkle Tree Builder
│   ├── m4_rs_encoder.py       # Reed-Solomon Encoder
│   ├── m5_profile.py          # Transfer Profile Selector
│   ├── m6_fountain_encoder.py # Fountain Encoder wrapper (uses IFountainEncoder)
│   ├── m7_multipass.py        # Multi-Pass Generator
│   ├── m8_interleaver.py      # Packet Interleaver
│   ├── m9_metadata.py         # Metadata + Auth Tag Generator (CRC32C + BLAKE3)
│   ├── m10_serializer.py      # Protocol Buffer Serializer
│   ├── m11_transmitter.py     # Rate-Controlled UDP Transmitter
│   └── pipeline.py            # Wires all sender modules into one callable
│
├── receiver/
│   ├── __init__.py
│   ├── m12_receiver.py        # UDP Receiver & Packet Buffer
│   ├── m13_validator.py       # Packet Validator + Decoder Limit Enforcement
│   ├── m14_auth_verifier.py   # Authentication Verifier (Ed25519 + BLAKE3-MAC)
│   ├── m15_pooler.py          # Multi-Pass Packet Pooler
│   ├── m16_fountain_decoder.py# Fountain Decoder wrapper (uses IFountainDecoder)
│   ├── m17_rs_decoder.py      # Reed-Solomon Decoder
│   ├── m18_merkle_verifier.py # Merkle Chunk Verifier
│   ├── m19_window_reassembler.py # Window-Level Reassembler
│   ├── m20_file_reassembler.py   # File Reassembler (windows → final file)
│   ├── m21_verifier.py        # SHA-256 + Merkle Root Final Verifier
│   ├── m22_quarantine.py      # Quarantine Pipeline + Transfer State Machine
│   ├── m23_storage.py         # Secure Storage Writer
│   └── pipeline.py            # Wires all receiver modules into one callable
│
├── tests/
│   ├── __init__.py
│   ├── test_fountain.py       # Unit tests: encoder, decoder, registry, multi-pass
│   ├── test_chunker.py        # Unit tests: chunking, padding, window boundaries
│   ├── test_merkle.py         # Unit tests: tree construction, proof verification
│   ├── test_rs.py             # Unit tests: RS encode/decode, gap recovery
│   ├── test_manifest.py       # Unit tests: manifest generation, serialization
│   ├── test_validator.py      # Unit tests: CRC32C, BLAKE3-MAC, limit enforcement
│   ├── test_pooler.py         # Unit tests: dedup, multi-pass pooling, timeouts
│   ├── test_pipeline_e2e.py   # End-to-end: sender → loopback → receiver
│   └── utils/
│       ├── __init__.py
│       └── loss_simulator.py  # Configurable packet loss/burst/corruption injection
│
├── .devcontainer/
│   └── devcontainer.json      # Codespaces environment spec
│
├── simulate_diode.py          # Main entry: launches sender + receiver as two processes
├── requirements.txt
├── setup.cfg                  # pytest config, coverage config
└── README.md
```

---

## DEPENDENCIES

```
# requirements.txt

# Serialization
protobuf>=4.25.0

# Reed-Solomon
reedsolo>=1.7.0

# Cryptography (Ed25519 signatures)
cryptography>=42.0.0

# BLAKE3 (fast cryptographic hashing)
blake3>=0.4.0

# Numerics (LT code probability math)
numpy>=1.26.0

# Testing
pytest>=8.0.0
pytest-cov>=4.0.0
```

---

## DEVCONTAINER

```json
// .devcontainer/devcontainer.json
{
  "name": "data-diode-dev",
  "image": "mcr.microsoft.com/devcontainers/python:3.11",
  "postCreateCommand": "pip install -r requirements.txt && sudo apt-get install -y protobuf-compiler",
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.pylance",
        "ms-python.debugpy",
        "zxh404.vscode-proto3"
      ]
    }
  }
}
```

---

## IMPLEMENTATION PHASES

Build in this exact order. Do not skip ahead. Each phase must be fully tested
before beginning the next phase.

```
PHASE 1 — Core Pipeline (end-to-end working transfer)
══════════════════════════════════════════════════════
Goal: get a file from sender to receiver with basic integrity check.

 Step 1   fountain/interface.py           IFountainEncoder, IFountainDecoder ABCs
 Step 2   fountain/lt_encoder.py          LT encode (Robust Soliton + XOR)
 Step 3   fountain/lt_decoder.py          Belief propagation peeling decoder
          → TEST: tests/test_fountain.py (all tests must pass before continuing)

 Step 4   common/models.py                All shared dataclasses
 Step 5   common/config.py               Constants, profile defaults
 Step 6   sender/m2_chunker.py            File → fixed-size padded chunks
          → TEST: tests/test_chunker.py

 Step 7   sender/m3_merkle.py             Merkle tree builder (SHA-256 leaves)
          → TEST: tests/test_merkle.py

 Step 8   sender/m0_manifest.py           Transfer manifest generation
 Step 9   common/proto/manifest.proto     Protobuf schema for manifest
 Step 10  common/proto/packet.proto       Protobuf schema for encoded packet
 Step 11  sender/m10_serializer.py        Protobuf serialize/deserialize
          → TEST: tests/test_manifest.py

 Step 12  sender/m11_transmitter.py       UDP send to 127.0.0.1:PORT
 Step 13  receiver/m12_receiver.py        UDP receive + ring buffer
 Step 14  receiver/m13_validator.py       CRC32C + schema + bounds check (basic)
 Step 15  receiver/m15_pooler.py          Packet pool per transfer_id
 Step 16  receiver/m16_fountain_decoder.py Decode chunks from unified pool
 Step 17  receiver/m20_file_reassembler.py Chunks → output file
 Step 18  receiver/m21_verifier.py        SHA-256 + Merkle root final check
 Step 19  simulate_diode.py               Two-process loopback, no loss
          → TEST: tests/test_pipeline_e2e.py (basic, no loss)
          ✓ MILESTONE: First complete file transfer end-to-end

PHASE 2 — Robustness Layer
══════════════════════════════════════════════════════
Goal: survive packet loss, burst loss, and large files.

 Step 20  sender/m5_profile.py            Hybrid profile selector (file size + criticality)
 Step 21  sender/m1_windowing.py          File → bounded windows
 Step 22  sender/m4_rs_encoder.py         Reed-Solomon encode per window
 Step 23  sender/m7_multipass.py          Multi-pass packet generation (independent seeds)
 Step 24  sender/m8_interleaver.py        Transmission order shuffle
 Step 25  sender/m6_fountain_encoder.py   Full fountain encoder wrapper (multi-pass aware)
 Step 26  receiver/m17_rs_decoder.py      RS gap recovery after fountain decode
 Step 27  receiver/m18_merkle_verifier.py Per-chunk Merkle hash verification
 Step 28  receiver/m19_window_reassembler Window-level reassembly + subtree verification
 Step 29  tests/utils/loss_simulator.py   Random loss, burst loss, corruption injection
          → TEST: tests/test_rs.py
          → TEST: tests/test_pooler.py
          → TEST: tests/test_pipeline_e2e.py (with loss scenarios)
          ✓ MILESTONE: File transfers survive 10% random loss + burst loss

PHASE 3 — Security Hardening
══════════════════════════════════════════════════════
Goal: authenticate sender, detect tampering, prevent DoS.

 Step 30  sender/m9_metadata.py           CRC32C + BLAKE3-MAC per packet + Ed25519 manifest signing
 Step 31  receiver/m14_auth_verifier.py   Ed25519 signature verify + BLAKE3-MAC verify
 Step 32  receiver/m13_validator.py       Add hard decoder limits (DoS guards)
 Step 33  receiver/m22_quarantine.py      Transfer state machine + quarantine logic
 Step 34  receiver/m23_storage.py         Secure storage writer (post-quarantine)
          → TEST: tests/test_validator.py (including DoS guard tests)
          ✓ MILESTONE: System rejects forged transfers, survives malformed streams

PHASE 4 — Optimisation (post-demo, future)
══════════════════════════════════════════════════════
 Step 35  fountain/raptorq_encoder.py     Real RaptorQ replacing stub (RFC 6330)
          → No other files change — drop-in via the interface
```

---

## MODULE SPECIFICATIONS

Below is the complete specification for every module. Build each module to
exactly this spec. Every module must have a module-level docstring explaining
its role and key design decisions.

---

### SENDER MODULES

---

#### `sender/m0_manifest.py` — Transfer Manifest Generator

**Role:** Generates the transfer manifest — a complete description of the
transfer that the receiver needs before it can configure its decoder.

**Why a separate manifest?**
Without a manifest, the receiver learns transfer parameters mid-stream. It
cannot pre-size the Tanner graph, cannot validate K and RS parameters against
its hard limits, and cannot set up window-level decode sessions before packets
arrive. Industrial data diode products always have a session header / manifest
as a separate transmission phase.

**Manifest is transmitted as Phase 0** — sent with 5× redundancy before any
data packets. Receiver waits for manifest decode before allocating any decoder
resources.

**Manifest fields:**
```python
@dataclass
class TransferManifest:
    transfer_id        : str       # UUID4, unique per transfer
    sender_node_id     : str       # configurable sender identifier
    protocol_version   : str       # e.g. "1.0.0" — schema versioning
    file_name          : str       # original filename
    file_size          : int       # bytes
    file_sha256        : str       # hex SHA-256 of original file
    chunk_size         : int       # bytes per chunk (fixed, except last padded)
    total_chunks       : int       # K — original chunks before RS
    rs_n               : int       # Reed-Solomon n parameter
    rs_k               : int       # Reed-Solomon k parameter
    num_passes         : int       # LT encoding passes
    overhead_ratio     : float     # per-pass overhead fraction
    interleave_depth   : int       # packet interleave stride
    window_size_bytes  : int       # bytes per window
    total_windows      : int       # number of windows
    merkle_root        : str       # hex Merkle root of all chunk hashes
    mime_type          : str       # file MIME type
    creation_timestamp : float     # Unix epoch, sender wall clock
    classification_level: str      # "standard" | "critical" | "classified"
    expiration_policy  : int       # seconds after which transfer is invalid
    ed25519_signature  : bytes     # Ed25519 sig over all above fields
```

**Transmission:** Serialized via Protobuf. Sent 5× (or profile-configured
redundancy multiplier) before data packets begin.

---

#### `sender/m1_windowing.py` — File Windowing Engine

**Role:** Divides large files into fixed-size windows so each window can be
independently encoded, transmitted, and decoded with bounded memory usage.

**Why windowing?**
A 10 GB file at 1200-byte chunks produces ~8.7 million source chunks. A Tanner
graph with 8.7 million nodes will exhaust RAM on any reasonable system. Windows
bound the graph size to a configurable maximum.

**Window sizing (set by m5_profile.py based on available RAM estimate):**
```
< 512 MB RAM budget  →  32 MB windows
512 MB – 2 GB        →  64 MB windows   (default)
> 2 GB               →  128 MB windows
```

**Each window is completely independent:**
- Own chunk set
- Own Merkle subtree (whose root feeds into global Merkle tree)
- Own RS encoding session
- Own fountain encode session(s)
- Own decode session on receiver side

**Global Merkle tree** is hierarchical: window Merkle roots are children of
the global root. End-to-end integrity is maintained across the whole file even
though processing is windowed.

---

#### `sender/m2_chunker.py` — File Analyzer & Chunker

**Role:** Reads a file window and splits it into fixed-size chunks. Pads the
last chunk to exactly chunk_size with zero bytes. Records padding length for
receiver to strip.

**Chunk size selection:**
```
chunk_size = MTU (1500) - IP header (20) - UDP header (8)
             - Protobuf overhead (~50) - metadata (~100)
           ≈ 1200 bytes   (safe default, configurable)
```

**Outputs:** list of bytes objects, all exactly chunk_size. The last chunk is
zero-padded. padding_length is recorded in the window manifest so the receiver
strips exactly the right number of bytes.

**Chunk IDs** are assigned as global offsets (not per-window) so the receiver
can detect any ordering or cross-window mix-up.

---

#### `sender/m3_merkle.py` — Merkle Tree Builder

**Role:** Builds a binary Merkle tree from a list of chunk hashes. Produces:
1. Per-chunk hash (SHA-256 of chunk bytes) — attached to each encoded packet
2. Window Merkle root — transmitted in window header
3. Global Merkle root — transmitted in transfer manifest

**Why Merkle over simple SHA-256?**
SHA-256 can only verify the whole file at the end. Merkle allows the receiver
to verify each chunk independently as it is decoded — before reassembly. If
chunk 47 fails its Merkle check, it is flagged corrupt (not just missing) and
treated as a loss for RS recovery. Partial transfers can be diagnosed precisely.

**Tree construction:**
```python
leaves = [sha256(chunk) for chunk in chunks]
# Pad to next power of 2 if needed (duplicate last leaf)
# Build bottom-up: parent = sha256(left_child + right_child)
# Root = single top-level hash
```

**Outputs:** MerkleTree dataclass with root (hex), leaves (list of hex hashes),
and a get_proof(chunk_id) method for individual chunk proof paths.

---

#### `sender/m4_rs_encoder.py` — Reed-Solomon Encoder

**Role:** Adds Reed-Solomon parity chunks to each window's chunk list before
fountain encoding. This creates a second independent recovery layer at the
chunk level (fountain codes recover at the packet level).

**Why RS + Fountain?**
These two layers protect against different failure modes:
- Fountain codes recover from **packet loss** (UDP layer, probabilistic)
- Reed-Solomon recovers from **chunk loss** (block layer, deterministic)

If fountain decode recovers 98% of chunks and 2% are still missing, RS parity
can reconstruct the remaining 2% deterministically — the file is complete.

**RS configuration (from Transfer Profile m5):**
```
File Size / Criticality   RS Config   Meaning
< 10 MB   / standard      RS(16, 2)   2 parity per 16 data chunks
< 10 MB   / critical      RS(16, 4)
10MB–1GB  / standard      RS(32, 4)   4 parity per 32 data chunks
10MB–1GB  / critical      RS(32, 6)
> 1 GB    / standard      RS(64, 6)
> 1 GB    / critical      RS(64, 8)
Any       / classified     RS(32, 8)   8 parity per 32 (25% overhead)
```

**Library:** `reedsolo` (pip install reedsolo). Use RSCodec class.

**Output:** Original chunks + parity chunks appended. Total = K' chunks.
K' is what fountain encoder receives as its source chunk count.

---

#### `sender/m5_profile.py` — Transfer Profile Selector

**Role:** Single configuration controller. Reads file size and criticality
level, outputs all tunable parameters for every downstream module. This is
the only place where robustness strategy is defined — changing a profile
here propagates automatically to all modules.

**Profile table:**
```python
PROFILES = {
    ("small",  "standard"):    Profile(passes=1, overhead=0.20, rs="RS(16,2)",  interleave=2,  header_redundancy=3),
    ("small",  "critical"):    Profile(passes=2, overhead=0.20, rs="RS(16,4)",  interleave=3,  header_redundancy=5),
    ("medium", "standard"):    Profile(passes=2, overhead=0.15, rs="RS(32,4)",  interleave=4,  header_redundancy=3),
    ("medium", "critical"):    Profile(passes=3, overhead=0.15, rs="RS(32,6)",  interleave=5,  header_redundancy=5),
    ("large",  "standard"):    Profile(passes=2, overhead=0.20, rs="RS(64,6)",  interleave=6,  header_redundancy=3),
    ("large",  "critical"):    Profile(passes=3, overhead=0.15, rs="RS(64,8)",  interleave=6,  header_redundancy=5),
    ("any",    "classified"):  Profile(passes=3, overhead=0.25, rs="RS(32,8)",  interleave=8,  header_redundancy=5),
}
# Size thresholds: small < 10MB, medium 10MB–1GB, large > 1GB
```

**Output:** Profile dataclass consumed by m0, m1, m4, m6, m7, m8, m9.

---

#### `sender/m6_fountain_encoder.py` — Fountain Encoder Wrapper

**Role:** Wraps IFountainEncoder to handle multi-pass encoding and pass_id
assignment. The pipeline calls this module — it does not call lt_encoder.py
directly. This keeps the pipeline clean and codec-agnostic.

**Codec selection:**
```python
from fountain.interface import get_encoder
encoder = get_encoder("lt")   # change to "raptorq" when ready — nothing else changes
```

**Multi-pass:**
- Calls encoder.encode(chunks, seed=SEED_A, overhead_ratio) for pass 0
- Calls encoder.encode(chunks, seed=SEED_B, overhead_ratio) for pass 1
- Calls encoder.encode(chunks, seed=SEED_C, overhead_ratio) for pass 2
- Sets pass_id on each packet accordingly
- Seeds are derived deterministically: seed_for_pass_i = hash(transfer_id + window_id + pass_i)

---

#### `sender/m7_multipass.py` — Multi-Pass Generator

**Role:** Generates independent, deterministic seeds for each pass of a given
transfer+window combination. Seeds must be:
1. Deterministic (same transfer_id + window_id → same seeds always)
2. Uncorrelated (seeds for different passes produce maximally different XOR combos)
3. Reproducible (stored in manifest so receiver can verify)

**Seed derivation:**
```python
import hashlib
def seed_for_pass(transfer_id: str, window_id: int, pass_id: int) -> int:
    raw = f"{transfer_id}:{window_id}:{pass_id}".encode()
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big")
```

This guarantees that pass 0 and pass 1 of the same window use completely
different PRNG sequences → different XOR combinations → uncorrelated loss coverage.

---

#### `sender/m8_interleaver.py` — Packet Interleaver

**Role:** Reorders the transmission sequence of encoded packets to spread burst
loss across the logical packet space.

**Why interleaving?**
Without interleaving, a 5-second network hiccup drops 500 consecutive packets
covering logical positions 300–800. That's a dense gap the decoder may not
bridge. With interleaving (stride S), those 500 physical-position packets are
spread across the entire logical space — no dense gap forms.

**Interleave algorithm (stride-based):**
```python
def interleave(packets, stride):
    # Transmit packet[0], packet[stride], packet[2*stride], ...
    # then packet[1], packet[stride+1], ...
    interleaved = []
    for offset in range(stride):
        interleaved.extend(packets[offset::stride])
    return interleaved
```

**Cross-pass interleaving:** Packets from different passes are also interleaved
together so a burst doesn't wipe an entire pass:
```
TX: [p0_passA][p0_passB][p1_passA][p1_passB][p2_passA][p2_passB]...
```

Stride is provided by Transfer Profile (m5).

---

#### `sender/m9_metadata.py` — Metadata + Auth Tag Generator

**Role:** Attaches the full security envelope to each packet before
serialization. Two cryptographic layers:

**Layer 1 — CRC32C (per packet, fast):**
- Computed over the serialized packet payload + all metadata fields
- Used by receiver for fast corrupt-packet rejection before any crypto
- CRC32C (Castagnoli) preferred over CRC32 — better polynomial, hardware-
  accelerated on x86 (SSE4.2) and ARM

**Layer 2 — BLAKE3-MAC (per packet, cryptographic):**
- BLAKE3(key=shared_secret, data=serialized_packet)
- Shared secret is a pre-configured symmetric key (set at deployment time)
- Catches adversarial tampering that CRC32C cannot detect
- BLAKE3 chosen over HMAC-SHA256: significantly faster, parallelizable,
  modern construction

**Ed25519 signature (per manifest, not per packet):**
- Signs: manifest_bytes + merkle_root + transfer_id
- Private key held by sender, public key pre-distributed to receiver
- Verifies sender authenticity — not just data integrity

**Full packet envelope:**
```
┌─────────────────────────────────────┐
│ transfer_id    (str, UUID)          │
│ window_id      (int)                │
│ pass_id        (int: 0,1,2)         │
│ packet_id      (int, within pass)   │
│ seed           (int, LT seed)       │
│ degree         (int)                │
│ chunk_ids      (list[int])          │
│ chunk_hash     (str, SHA-256 hex)   │  ← Merkle leaf for this chunk group
│ timestamp      (float, epoch)       │
│ total_K        (int, original K)    │
│ total_K_prime  (int, K + RS parity) │
│ rs_n, rs_k     (int, int)           │
│ schema_version (str)                │
│ crc32c         (int)                │  ← fast corruption gate
│ blake3_mac     (bytes)              │  ← tamper detection
├─────────────────────────────────────┤
│ ENCODED PAYLOAD (bytes)             │
└─────────────────────────────────────┘
```

---

#### `sender/m10_serializer.py` — Protocol Buffer Serializer

**Role:** Serializes/deserializes EncodedPacket and TransferManifest objects
to/from binary using Protocol Buffers.

**Why Protobuf?**
- Deterministic binary encoding (no JSON/pickle ambiguity)
- Strongly typed fields — schema version enforced
- Compact encoding — important at packet scale
- Language-agnostic — receiver can be reimplemented in any language
- Forward-compatible with `reserved` field support

**Proto schemas** (define in common/proto/):
```protobuf
// packet.proto
syntax = "proto3";
message EncodedPacketProto {
  string transfer_id    = 1;
  int32  window_id      = 2;
  int32  pass_id        = 3;
  int32  packet_id      = 4;
  int64  seed           = 5;
  int32  degree         = 6;
  repeated int32 chunk_ids = 7;
  string chunk_hash     = 8;
  double timestamp      = 9;
  int32  total_k        = 10;
  int32  total_k_prime  = 11;
  int32  rs_n           = 12;
  int32  rs_k           = 13;
  string schema_version = 14;
  fixed32 crc32c        = 15;
  bytes  blake3_mac     = 16;
  bytes  payload        = 17;
}
```

```protobuf
// manifest.proto
syntax = "proto3";
message TransferManifestProto {
  string transfer_id         = 1;
  string sender_node_id      = 2;
  string protocol_version    = 3;
  string file_name           = 4;
  int64  file_size           = 5;
  string file_sha256         = 6;
  int32  chunk_size          = 7;
  int32  total_chunks        = 8;
  int32  rs_n                = 9;
  int32  rs_k                = 10;
  int32  num_passes          = 11;
  double overhead_ratio      = 12;
  int32  interleave_depth    = 13;
  int64  window_size_bytes   = 14;
  int32  total_windows       = 15;
  string merkle_root         = 16;
  string mime_type           = 17;
  double creation_timestamp  = 18;
  string classification_level = 19;
  int32  expiration_policy   = 20;
  bytes  ed25519_signature   = 21;
}
```

**Compile with:** `protoc --python_out=common/proto/generated common/proto/*.proto`

---

#### `sender/m11_transmitter.py` — Rate-Controlled UDP Transmitter

**Role:** Sends serialized packets over UDP to the receiver address. Implements
rate control to prevent buffer overflow on the receiver side.

**Transmission sequence:**
```
1. Manifest packets     (profile.header_redundancy copies, e.g. 5×)
2. Window 0, Pass 0 packets  (interleaved order)
3. Window 0, Pass 1 packets  (interleaved order, if num_passes >= 2)
4. Window 0, Pass 2 packets  (interleaved order, if num_passes >= 3)
5. Window 1, Pass 0 packets  ...
   ... (repeat for all windows)
N. Transfer footer      (3× copies: transfer_id + "END" marker)
```

**Rate control:**
```python
# Configurable packets per second
# Default: 10,000 pps — adjust based on MTU and channel speed
inter_packet_gap = 1.0 / packets_per_second
time.sleep(inter_packet_gap)   # between each send
```

**Socket config:**
```python
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
# Sender-only socket — no bind, no recvfrom, ever
```

---

### RECEIVER MODULES

---

#### `receiver/m12_receiver.py` — UDP Receiver & Packet Buffer

**Role:** Listens on a fixed UDP port, ingests raw datagrams, stores them in a
per-transfer ring buffer.

**CRITICAL RULE: NO OUTBOUND TRAFFIC EVER.**
The receiver socket is created with `socket.socket(AF_INET, SOCK_DGRAM)` and
`bind((HOST, PORT))`. `recvfrom()` only. `sendto()` is never called.
In software simulation this is application-level enforcement. On real hardware
the physical diode enforces it at the optical/electrical layer.

**Ring buffer design:**
- Per transfer_id: bounded deque of raw packet bytes
- Max size: configurable (default 500,000 packets)
- Overflow policy: drop oldest unvalidated packets (not decoded data)
- Multiple concurrent transfer_ids supported (diode may receive overlapping
  transfers in production)

**Socket config:**
```python
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
sock.bind(("0.0.0.0", PORT))
# recvfrom() in a loop — single thread or asyncio
```

---

#### `receiver/m13_validator.py` — Packet Validator + Decoder Limit Enforcement

**Role:** Per-packet validation gate. Every check must pass before a packet
enters the decode pool. Rejects silently — no error response ever sent.

**Validation sequence (order matters — cheap checks first):**

1. **CRC32C check** — recompute over packet bytes, compare to crc32c field.
   Drop if mismatch. This is the fast corruption gate.

2. **Schema version check** — verify schema_version field matches supported
   versions. Drop if unknown.

3. **Protobuf structural check** — verify all required fields present and
   field types correct. Drop if malformed.

4. **transfer_id whitelist** — verify transfer_id is in the set of currently
   expected transfers (populated from manifest). Drop if unknown.

5. **Timestamp replay window** — verify packet timestamp is within
   `[transfer_start - 60s, transfer_start + max_transfer_duration]`.
   Drop if outside window. This blocks replay attacks using captured packets.

6. **pass_id bounds** — verify pass_id ∈ [0, num_passes - 1] from manifest.
   Drop if out of range.

7. **packet_id bounds** — verify packet_id is within expected range for the
   pass. Drop if out of range.

**Hard decoder limits (DoS guards) — checked against manifest values:**
```python
MAX_DEGREE          = 50          # packets claiming degree > this → drop
MAX_K               = 1_000_000  # manifest claiming K > this → reject transfer
MAX_TRANSFER_SIZE   = 100 * 1024**3  # 100 GB hard ceiling
MAX_PASSES          = 3          # manifest claiming > 3 passes → reject
MAX_CONCURRENT      = 4          # max simultaneous active transfers
MAX_DECODE_TIME     = 300        # seconds before window decode is abandoned
MAX_MEMORY_PER_SESS = 512 * 1024**2  # 512 MB per decode session
```

If a manifest field exceeds any hard limit, the **entire transfer** is rejected
immediately — no packets are processed.

**Rejected packets** are logged with reason code for post-transfer diagnostics.
Rejection reasons: CRC_FAIL, SCHEMA_UNKNOWN, MALFORMED, UNKNOWN_TRANSFER,
REPLAY, PASS_OOB, PACKET_OOB, DEGREE_EXCEEDED.

---

#### `receiver/m14_auth_verifier.py` — Authentication Verifier

**Role:** Verifies the two cryptographic authentication layers:

**Layer 1 — BLAKE3-MAC verification (per packet):**
```python
import blake3
expected_mac = blake3.blake3(packet_bytes, key=SHARED_SECRET).digest()
if not hmac.compare_digest(expected_mac, packet.blake3_mac):
    drop(packet, reason="BLAKE3_MAC_FAIL")
```
Constant-time comparison (hmac.compare_digest) to prevent timing attacks.
Shared secret is a 32-byte key configured at deployment time (environment
variable or key file, never hardcoded).

**Layer 2 — Ed25519 signature verification (per manifest):**
```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
public_key.verify(manifest.ed25519_signature, manifest_signed_bytes)
```
Public key is pre-distributed to the receiver out-of-band (deployment config).
If signature fails → entire transfer rejected.

**Failure behavior:** Silent drop (per packet) or full transfer rejection
(manifest signature failure). No error sent. Failure logged.

---

#### `receiver/m15_pooler.py` — Multi-Pass Packet Pooler

**Role:** Aggregates validated packets from all passes of the same
transfer_id + window_id into a single unified decode pool.

**Why a unified pool?**
The LT decoder sees one pool — not separate passes. Packets from pass 0 and
pass 1 that cover different XOR combinations of the same chunks complement
each other in the Tanner graph. Keeping them separate and decoding independently
wastes the cross-pass recovery benefit.

**Pool operations:**
- Deduplication by (window_id, pass_id, packet_id) — exact duplicates dropped
- Pool capacity: max_packets = K_prime × num_passes × 1.5 (soft ceiling)
- Readiness check: trigger decode when pool_size ≥ K_prime × 1.05 OR timeout
- Timeout trigger: if no new packets received for T seconds → decode anyway
  with whatever is in the pool

**Pool structure:**
```python
@dataclass
class TransferPool:
    transfer_id : str
    window_id   : int
    packets     : dict[tuple[int,int,int], EncodedPacket]  # (window,pass,packet) → pkt
    created_at  : float
    last_updated: float
    status      : str   # "collecting" | "decoding" | "done" | "failed"
```

---

#### `receiver/m16_fountain_decoder.py` — Fountain Decoder Wrapper

**Role:** Wraps IFountainDecoder. Calls decoder.decode(pool, K_prime).
Returns DecodeResult with recovered chunks and list of missing chunk_ids.

**Codec selection:**
```python
from fountain.interface import get_decoder
decoder = get_decoder("lt")   # change to "raptorq" when ready
```

Missing chunk_ids from DecodeResult are passed directly to m17_rs_decoder.py.

---

#### `receiver/m17_rs_decoder.py` — Reed-Solomon Decoder

**Role:** Takes fountain decode output (some chunks may still be None) and
uses RS parity chunks to reconstruct missing data chunks.

**Input:** list[bytes | None] of length K_prime (K data + parity chunks)
**Output:** list[bytes | None] of length K (data chunks only, parity removed)

**RS can reconstruct up to `rs_k_parity` missing chunks per RS block.**
If more chunks are missing than parity allows → that RS block is unrecoverable
→ its chunk_ids added to the final missing_ids list → flagged for Merkle verifier.

**Library:** `reedsolo.RSCodec` — same library as sender, same parameters.

---

#### `receiver/m18_merkle_verifier.py` — Merkle Chunk Verifier

**Role:** Verifies every recovered chunk against its Merkle leaf hash BEFORE
reassembly. Catches corruption that CRC32C + BLAKE3-MAC missed (e.g., CRC32C
collision, or a bug in the decode logic itself).

**Per-chunk verification:**
```python
for chunk_id, chunk_bytes in enumerate(recovered_chunks):
    if chunk_bytes is None:
        continue
    expected_hash = manifest.merkle_leaf_hashes[chunk_id]
    actual_hash   = sha256(chunk_bytes).hexdigest()
    if actual_hash != expected_hash:
        # Chunk is corrupt even though it "decoded" successfully
        # Treat as missing → flag for RS recovery or final failure
        recovered_chunks[chunk_id] = None
        log(f"Merkle mismatch on chunk {chunk_id}")
```

**Post-verification:** Rebuild Merkle tree from verified chunk hashes.
Compare computed root vs received Merkle root from manifest.
Mismatch → reject entire transfer (something is fundamentally wrong).

---

#### `receiver/m19_window_reassembler.py` — Window Reassembler

**Role:** Reassembles verified chunks into a complete window byte sequence.
Strips zero-padding from the last chunk of the window.

**Ordering:** By chunk_id (global offset), NOT by arrival order.
UDP gives no ordering guarantees — arrival order is meaningless.

**Output:** Raw bytes for this window. Passed to m20_file_reassembler.py.

**Failure behavior:** If any chunk is still None after Merkle verification →
window is INCOMPLETE. Window status set to FAILED. Transfer-level failure
logged. File reassembly is halted.

---

#### `receiver/m20_file_reassembler.py` — File Reassembler

**Role:** Concatenates all window byte sequences in window_id order to produce
the final reconstructed file. Writes to a temporary file in the quarantine
directory (not secure storage yet).

**All windows must be COMPLETE before this module runs.**
If any window is FAILED → file reassembly does not proceed → transfer marked
FAILED.

---

#### `receiver/m21_verifier.py` — SHA-256 + Merkle Root Final Verifier

**Role:** Two independent end-to-end integrity checks on the fully reassembled
file.

**Check 1 — Global Merkle Root:**
Rebuild the global Merkle tree from all window Merkle roots.
Compare computed global root vs manifest.merkle_root.
✓ Match → structural integrity confirmed

**Check 2 — SHA-256:**
Compute SHA-256 of the full reassembled file bytes.
Compare vs manifest.file_sha256.
✓ Match → byte-level integrity confirmed

**Both must pass.** Either failure → file rejected → quarantine notified.

Having both is intentional: Merkle catches chunk/window structural issues,
SHA-256 catches any reassembly logic bugs that Merkle might not catch.

---

#### `receiver/m22_quarantine.py` — Quarantine Pipeline & Transfer State Machine

**Role:** Manages the trust boundary between the receive pipeline and secure
storage. No file reaches secure storage without passing through quarantine.

**Transfer state machine:**
```
RECEIVING   → packets arriving, pool building
DECODING    → fountain + RS decode in progress
VERIFYING   → Merkle + SHA checks running
QUARANTINE  → passed decode+verify, under content inspection
ACCEPTED    → moved to secure storage
FAILED      → logged, held in forensic buffer, alert raised
EXPIRED     → transfer timed out before completion
```

**Quarantine checks (configurable, pluggable):**
- File size matches manifest.file_size exactly
- MIME type matches manifest.mime_type
- Content policy check (placeholder — hook for antivirus/DLP integration)
- Expiration policy: reject if current_time > manifest.creation_timestamp + manifest.expiration_policy

**On ACCEPTED:** call m23_storage.py to move file to secure storage.
**On FAILED:** retain file in forensic buffer (do NOT delete), raise alert,
log full transfer diagnostics.

---

#### `receiver/m23_storage.py` — Secure Storage Writer

**Role:** Moves a quarantine-cleared file into the designated secure storage
directory with an immutable transfer receipt.

**Operations:**
1. Verify file still passes SHA-256 (re-check after quarantine, before move)
2. Move file from quarantine to secure storage (atomic rename where possible)
3. Write transfer receipt:
   ```json
   {
     "transfer_id": "...",
     "file_name": "...",
     "file_sha256": "...",
     "received_at": 1234567890.0,
     "sender_node_id": "...",
     "classification_level": "...",
     "merkle_root": "...",
     "windows_received": 16,
     "packets_received": 18420,
     "packets_dropped": 143
   }
   ```
4. Set file permissions: 0o440 (owner read, group read, no write, no execute)
5. Log ACCEPTED event with full transfer metadata

---

### SIMULATION ENTRY POINT

---

#### `simulate_diode.py` — Two-Process Loopback Simulator

**Role:** Launches sender and receiver as two independent Python processes
communicating over UDP loopback, simulating a data diode in software.

**Design:**
```python
import multiprocessing
from sender.pipeline import run_sender
from receiver.pipeline import run_receiver

if __name__ == "__main__":
    # Parse args: input file, criticality level, loss_rate, burst_size
    
    receiver_proc = multiprocessing.Process(target=run_receiver, args=(config,))
    sender_proc   = multiprocessing.Process(target=run_sender,   args=(file_path, config))
    
    receiver_proc.start()
    time.sleep(0.5)   # give receiver time to bind socket
    sender_proc.start()
    
    sender_proc.join()
    receiver_proc.join(timeout=300)
```

**The receiver process NEVER communicates back to the sender process.**
No shared memory, no pipes, no queues between them. They communicate only
via UDP socket — one direction only.

**CLI usage:**
```bash
python simulate_diode.py --file /path/to/file \
                          --criticality critical \
                          --loss-rate 0.05 \
                          --burst-size 50 \
                          --output-dir /tmp/secure_storage
```

---

#### `tests/utils/loss_simulator.py` — Packet Loss Simulator

**Role:** Wraps the receiver buffer to inject configurable packet loss for
testing. Never used in production — test utility only.

**Modes:**
```python
class LossSimulator:
    def random_loss(self, packets, rate):
        """Drop each packet with probability `rate`."""

    def burst_loss(self, packets, burst_start_frac, burst_length):
        """Drop `burst_length` consecutive packets starting at `burst_start_frac`."""

    def corrupt(self, packets, rate):
        """Randomly flip bits in `rate` fraction of packets (tests CRC rejection)."""

    def duplicate(self, packets, rate):
        """Duplicate `rate` fraction of packets (tests pooler deduplication)."""

    def reorder(self, packets, window_size):
        """Randomly reorder packets within a sliding window (tests ordering robustness)."""
```

---

## CODING STANDARDS

These apply to every file in the project. Claude Code must follow all of them.

### Structure
- Every module file starts with a module-level docstring explaining:
  1. What this module does (one sentence)
  2. Why it exists (the problem it solves)
  3. Key design decisions and trade-offs
- Every class has a class-level docstring
- Every public method has a docstring with Parameters and Returns sections
- No function longer than 60 lines — split into helpers if needed

### Typing
- Full type hints on all function signatures: `def encode(self, chunks: list[bytes], seed: int) -> list[EncodedPacket]:`
- Use `from __future__ import annotations` at the top of every file
- Dataclasses for all data transfer objects (`@dataclass`)
- No `Any` types unless absolutely unavoidable

### Error handling
- Never silently swallow exceptions
- Validation functions raise `ValueError` with descriptive messages
- Security-sensitive drops (packet validation) are logged, not raised
- No bare `except:` clauses — always catch specific exception types

### Logging
- Use Python standard `logging` module, never `print()` in production code
- Every module gets its own logger: `logger = logging.getLogger(__name__)`
- Log levels: DEBUG for per-packet detail, INFO for transfer-level events,
  WARNING for recoverable issues, ERROR for unrecoverable failures

### Testing
- Every module has a corresponding test file
- Tests are grouped in classes by category (e.g., TestEncoding, TestDoSGuards)
- Every test has a one-line docstring stating what it verifies
- Test edge cases explicitly: empty input, single element, max size, corrupt input
- Use `pytest.raises` for all expected exceptions
- No test depends on another test's state — fully isolated

### Security
- No secrets hardcoded — all keys via environment variables or config files
- `hmac.compare_digest()` for all MAC comparisons (timing-attack safe)
- Receiver socket: `recvfrom()` only, `sendto()` never called, not even in tests
- Decoder hard limits enforced before any graph memory is allocated

---

## KEY INVARIANTS — NEVER VIOLATE THESE

```
1. Receiver never sends. No outbound socket. No exceptions.

2. The fountain interface (IFountainEncoder, IFountainDecoder) is the only
   way the pipeline accesses fountain coding. lt_encoder.py and lt_decoder.py
   are never imported directly by pipeline code.

3. Manifest is always transmitted before data packets. Receiver ignores data
   packets for an unknown transfer_id until the manifest is received.

4. Decoder hard limits are checked BEFORE any memory is allocated for decode.
   A malicious manifest that claims K=10,000,000 is rejected before any
   Tanner graph nodes are created.

5. No file reaches secure storage (m23) without passing:
   - CRC32C per packet (m13)
   - BLAKE3-MAC per packet (m14)
   - Ed25519 manifest signature (m14)
   - Fountain decode (m16)
   - RS decode (m17)
   - Merkle per-chunk verification (m18)
   - SHA-256 + Merkle root final check (m21)
   - Quarantine policy (m22)

6. All chunks are equal size. Last chunk zero-padded. Padding length stored
   in manifest. Receiver strips exactly padding_length bytes from last chunk.

7. Different passes use different seeds. Seeds derived from
   hash(transfer_id + window_id + pass_id). Never reuse a seed.
```

---