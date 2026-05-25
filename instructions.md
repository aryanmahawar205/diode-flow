# Data Diode — Complete Build & Fix Guide for Claude Code
# =============================================================================
# Single unified instruction guide.
# Covers: bug fixes, performance, GB-scale streaming, compression, all modules.
#
# Context: A partial implementation exists (Phase 1 mostly done, Phase 2 started).
# This guide tells you exactly what to fix, what to add, and in what order.
# Do NOT rewrite from scratch. Fix specific issues as listed per module.
# =============================================================================

---

## WHAT YOU ARE BUILDING

A **software-only Data Diode system** in Python that enforces strictly one-way
data transfer — sender to receiver, nothing back. Used in critical infrastructure
and classified environments.

**Must handle:** files from 1KB to 10GB+, reliably, without retransmission.
**Must run on:** GitHub Codespaces (Ubuntu, 2 CPU, 8GB RAM).
**Simulated diode:** two Python processes on UDP loopback (127.0.0.1).
**One-way rule:** receiver socket calls `recvfrom()` only — `sendto()` never
called, not even in tests.

---

## WHY THE CURRENT IMPLEMENTATION IS SLOW

A 30MB file timed out after 10 minutes. Root causes in order of severity:

```
CAUSE 1 — Python byte-by-byte XOR in fountain encoder/decoder
  30MB / 1200B chunks = 25,000 chunks
  Each encoded packet XORs chunks byte-by-byte in a Python loop
  = 30 million individual Python operations just for encoding
  FIX: numpy vectorized XOR — 100× faster, one operation per chunk

CAUSE 2 — Decoder re-derives chunk_ids by re-running PRNG
  EncodedPacket is missing chunk_ids field
  Decoder re-runs Robust Soliton sampling to reconstruct which chunks were XOR'd
  This is both slow AND produces wrong results (global random state issue)
  FIX: store chunk_ids in EncodedPacket at encode time, decoder reads directly

CAUSE 3 — Global random.seed() corrupts shared PRNG state
  random.seed(x) sets module-level state — any concurrent code corrupts it
  FIX: random.Random(seed) instance per encode call

CAUSE 4 — Merkle proof O(N) parent scan at every tree level
  get_merkle_proof() scans entire tree dict at each of log2(N) levels
  For 25,000 chunks: 25,000 × 15 scans = 375,000 comparisons per proof
  FIX: build reverse lookup dict once — O(1) per level

CAUSE 5 — Wrong Robust Soliton formula
  Current spike term: c * sqrt(M) / (M * d * S) — nonstandard
  Correct: R / (d * K) for d < K/R, where R = c * log(K/delta) * sqrt(K)
  Wrong distribution degrades recovery at large K

CAUSE 6 — No compression
  A 30MB text file → ~8MB with lz4 (3-4× ratio)
  Fewer chunks, fewer packets, faster everything
  FIX: add streaming lz4 compression before chunking

CAUSE 7 — RS encoder is fake (duplicates last chunk instead of real parity)
  Produces wrong recovery data — silently corrupts files
  FIX: use reedsolo.RSCodec properly

FOR GB-SCALE FILES — additional architectural issues:
  Sender buffers all windows in RAM before sending (breaks at ~500MB)
  Receiver buffers all decoded windows in RAM (breaks at ~1GB)
  SHA-256, compression, assembly all load whole file (breaks at 2GB+)
  FIX: streaming pipeline — one window at a time, disk-backed storage
```

---

## COMPLETE FILE STRUCTURE

```
data_diode/
│
├── common/
│   ├── __init__.py
│   ├── config.py              # UPDATED: profiles, 2-pass cap, compression config
│   └── models.py              # UPDATED: EncodedPacket expanded, TransferProgress added
│
├── fountain/
│   ├── __init__.py            # Unchanged
│   ├── interface.py           # FIXED: EncodedPacket gets chunk_ids, packet_id, pass_id
│   ├── lt_encoder.py          # FIXED: numpy XOR, random.Random, correct RS, chunk_ids
│   ├── lt_decoder.py          # FIXED: reads chunk_ids directly, numpy XOR, set operations
│   └── raptorq_stub.py        # Unchanged
│
├── sender/
│   ├── __init__.py
│   ├── m0_compress.py         # NEW: streaming lz4 compression
│   ├── m0_manifest.py         # UPDATED: compression fields in manifest
│   ├── m1_windowing.py        # UPDATED: proportional window sizing
│   ├── m2_chunker.py          # Unchanged (correct)
│   ├── m3_merkle.py           # FIXED: O(1) proof, correct left/right ordering,
│   │                          #        streaming global root computation
│   ├── m4_rs_encoder.py       # FIXED: real reedsolo, not fake duplication
│   ├── m5_profile.py          # UPDATED: max 2 passes, performance-tuned
│   ├── m6_fountain_encoder.py # FIXED: import paths, return type, codec param
│   ├── m7_multipass.py        # Unchanged (correct)
│   ├── m8_interleaver.py      # FIXED: accepts EncodedPacket, skips empty passes
│   ├── m9_metadata.py         # FIXED: crcmod at module level, hmac.compare_digest,
│   │                          #        MAC covers metadata + payload
│   ├── m10_serializer.py      # FIXED: add serialize_packet/deserialize_packet,
│   │                          #        crcmod at module level
│   ├── m11_transmitter.py     # FIXED: send_transfer(), sleep-based rate control
│   └── pipeline.py            # REWRITE: streaming one-window-at-a-time pipeline
│
├── receiver/
│   ├── __init__.py
│   ├── m12_receiver.py        # FIXED: per-transfer buffers, correct max_packet_size
│   ├── m13_validator.py       # FIXED: all hard limits, timestamp replay, memory budget
│   ├── m14_auth_verifier.py   # Unchanged spec
│   ├── m15_pooler.py          # FIXED: stores EncodedPacket, readiness trigger,
│   │                          #        activity-based TTL, pool size cap
│   ├── m16_fountain_decoder.py# FIXED: unified pool (NOT per-pass), correct signature
│   ├── m17_rs_decoder.py      # FIXED: real reedsolo decode
│   ├── m18_merkle_verifier.py # FIXED: real proof traversal, uses models.py types
│   ├── m19_window_reassembler.py # FIXED: global chunk_id offset
│   ├── m20_file_reassembler.py   # REWRITE: disk-based streaming assembly
│   ├── m21_verifier.py        # FIXED: real Merkle root check, streaming SHA-256,
│   │                          #        hmac.compare_digest
│   ├── m22_quarantine.py      # Unchanged spec
│   ├── m23_storage.py         # Unchanged spec
│   ├── m24_decompress.py      # NEW: streaming lz4 decompression + verify
│   └── pipeline.py            # REWRITE: streaming disk-backed pipeline
│
├── tests/
│   ├── __init__.py
│   ├── test_fountain.py       # UPDATED: chunk_ids checks, empty pool graceful
│   ├── test_chunker.py        # UPDATED: fix LossScenario field, classified key
│   ├── test_merkle.py         # Unchanged
│   ├── test_rs.py             # Unchanged
│   ├── test_compress.py       # NEW: compression round-trip, should_compress()
│   ├── test_manifest.py       # Unchanged
│   ├── test_validator.py      # Unchanged
│   ├── test_pooler.py         # Unchanged
│   ├── test_pipeline_e2e.py   # UPDATED: add large file test (100MB+)
│   └── utils/
│       ├── __init__.py
│       └── loss_simulator.py  # FIXED: random.Random instances, burst stat bug
│
├── .devcontainer/
│   └── devcontainer.json
├── simulate_diode.py          # Unchanged structure — updated to use streaming pipeline
├── requirements.txt           # UPDATED: add lz4, crcmod, psutil
├── setup.cfg
└── README.md
```

---

## UPDATED DEPENDENCIES

```
# requirements.txt

protobuf>=4.25.0
reedsolo>=1.7.0
cryptography>=42.0.0
blake3>=0.4.0
numpy>=1.26.0       # critical — fountain XOR performance
crcmod>=1.7         # required, not optional — must be declared
lz4>=4.3.2          # new — streaming compression
psutil>=5.9.0       # new — memory budget enforcement
pytest>=8.0.0
pytest-cov>=4.0.0
```

---

## FIX 1 — EncodedPacket (fountain/interface.py)

This is the most critical structural fix. Every other module depends on it.
Apply this first before touching anything else.

```python
@dataclass
class EncodedPacket:
    """One fountain-encoded packet produced by encoder, consumed by decoder."""
    packet_id          : int        # unique within pass — for deduplication in pooler
    pass_id            : int        # which transmission pass (0 or 1)
    seed               : int        # PRNG seed used for this pass
    degree             : int        # number of source chunks XOR'd
    chunk_ids          : list[int]  # WHICH chunks were XOR'd — decoder reads directly
    data               : bytes      # XOR'd payload bytes
    source_chunk_count : int        # K' = original K + RS parity chunks

@dataclass
class DecodeResult:
    """Result of a fountain decode attempt."""
    chunks          : list[bytes | None]  # None = chunk not recovered
    success         : bool
    recovered_count : int
    missing_ids     : list[int]           # chunk_ids still missing after decode
    packets_used    : int
```

Also confirm `list_encoders()` and `list_decoders()` exist in interface.py
(currently imported by `__init__.py` but may not be defined). Add if missing:
```python
def list_encoders() -> list[str]:
    return list(_encoder_registry.keys())

def list_decoders() -> list[str]:
    return list(_decoder_registry.keys())
```

---

## FIX 2 — LT Encoder (fountain/lt_encoder.py)

Four specific fixes. Apply all four together.

### Fix A — Correct Robust Soliton Distribution

```python
import math

def _robust_soliton(K: int, c: float = 0.03, delta: float = 0.02) -> list[float]:
    """
    Correct Robust Soliton Distribution.
    c=0.03, delta=0.02 are standard production parameters.
    """
    R     = c * math.log(K / delta) * math.sqrt(K)
    pivot = max(1, int(math.floor(K / R)))

    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))

    tau = [0.0] * (K + 1)
    for d in range(1, pivot):
        tau[d] = R / (d * K)
    if pivot >= 1:
        tau[pivot] = (R * math.log(R / delta)) / K

    mu_raw = [rho[d] + tau[d] for d in range(K + 1)]
    Z = sum(mu_raw[1:])
    return [0.0] + [v / Z for v in mu_raw[1:]]


def _build_cdf(pmf: list[float]) -> list[float]:
    cdf, running = [0.0] * len(pmf), 0.0
    for i, p in enumerate(pmf):
        running += p
        cdf[i] = running
    return cdf


def _sample_degree(cdf: list[float], rng: random.Random) -> int:
    u = rng.random()
    lo, hi = 1, len(cdf) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cdf[mid] < u: lo = mid + 1
        else:             hi = mid
    return lo
```

### Fix B — random.Random instance (not global state)

```python
def encode(self, chunks: list[bytes], seed: int, overhead_ratio: float) -> list[EncodedPacket]:
    K_prime    = len(chunks)
    chunk_size = len(chunks[0])
    n_packets  = math.ceil(K_prime * (1.0 + overhead_ratio))

    mu  = _robust_soliton(K_prime)
    cdf = _build_cdf(mu)
    rng = random.Random(seed)    # ← instance, not global state

    encoded = []
    for packet_id in range(n_packets):
        degree    = min(_sample_degree(cdf, rng), K_prime)
        chunk_ids = sorted(rng.sample(range(K_prime), degree))
        # ... XOR and append
```

### Fix C — numpy XOR (performance)

```python
import numpy as np

# Inside the encode loop, replace byte-by-byte XOR with:
payload = np.zeros(chunk_size, dtype=np.uint8)
for idx in chunk_ids:
    payload ^= np.frombuffer(chunks[idx], dtype=np.uint8)
data = payload.tobytes()
```

### Fix D — Store chunk_ids in EncodedPacket

```python
encoded.append(EncodedPacket(
    packet_id          = packet_id,
    pass_id            = 0,           # caller sets actual pass_id after
    seed               = seed,
    degree             = degree,
    chunk_ids          = chunk_ids,   # ← stored explicitly
    data               = data,
    source_chunk_count = K_prime,
))
```

---

## FIX 3 — LT Decoder (fountain/lt_decoder.py)

Four specific fixes.

### Fix A — Read chunk_ids directly (not re-derive)

```python
def decode(self, packets: list[EncodedPacket], K_prime: int,
           max_degree: int = 50) -> DecodeResult:

    # DoS guard: degree cap
    safe_packets = [p for p in packets if 1 <= p.degree <= max_degree]

    if not safe_packets:
        return DecodeResult(
            chunks=[None] * K_prime, success=False,
            recovered_count=0, missing_ids=list(range(K_prime)), packets_used=0
        )

    # Build graph — read chunk_ids directly from packet
    recovered       = [None] * K_prime
    packet_payload  = []
    packet_chunks   = []          # list of set[int]
    chunk_to_packets = [set() for _ in range(K_prime)]

    for pi, pkt in enumerate(safe_packets):
        valid_ids = [cid for cid in pkt.chunk_ids if 0 <= cid < K_prime]
        if len(valid_ids) != pkt.degree:
            continue    # malformed packet
        packet_payload.append(bytearray(pkt.data))
        packet_chunks.append(set(valid_ids))
        cur_pi = len(packet_payload) - 1
        for cid in valid_ids:
            chunk_to_packets[cid].add(cur_pi)
```

### Fix B — numpy XOR in peeling loop

```python
import numpy as np

# In the peeling loop, replace:
for j in range(chunk_size):
    residual[j] ^= known[j]

# With:
arr_r = np.frombuffer(packet_payload[other_pi], dtype=np.uint8).copy()
arr_k = np.frombuffer(recovered[chunk_id],      dtype=np.uint8)
arr_r ^= arr_k
packet_payload[other_pi] = bytearray(arr_r.tobytes())
```

### Fix C — set.discard() instead of list.remove()

```python
# Already using set for packet_chunks — discard is O(1)
packet_chunks[other_pi].discard(chunk_id)   # not .remove()
```

### Fix D — Return graceful result on empty pool

```python
if not packets:
    return DecodeResult(
        chunks=[None] * K_prime, success=False,
        recovered_count=0, missing_ids=list(range(K_prime)), packets_used=0
    )
```

---

## FIX 4 — Merkle Tree (sender/m3_merkle.py)

Two fixes: correct proof ordering, O(1) proof generation.

### Fix A — Build reverse lookup at tree construction time

```python
def build_merkle_tree(chunks: list[bytes]) -> tuple:
    """Returns (tree, child_to_parent, sibling_map, is_left_child)."""
    # ... existing tree construction unchanged ...

    # Build reverse lookup after tree is complete
    child_to_parent = {}
    sibling_map     = {}
    is_left_child   = {}

    for node in tree.values():
        if node.left_child and node.right_child:
            child_to_parent[node.left_child]  = node.hash
            child_to_parent[node.right_child] = node.hash
            sibling_map[node.left_child]      = node.right_child
            sibling_map[node.right_child]     = node.left_child
            is_left_child[node.left_child]    = True    # this node IS the left child
            is_left_child[node.right_child]   = False   # this node IS the right child

    return tree, child_to_parent, sibling_map, is_left_child
```

### Fix B — O(log N) proof + correct left/right ordering

```python
def get_merkle_proof(tree_data: tuple, chunk_index: int,
                     chunks: list[bytes]) -> list[MerkleProofStep]:
    tree, child_to_parent, sibling_map, is_left_child = tree_data
    current = _sha256_hash(chunks[chunk_index])
    proof   = []

    while current in child_to_parent:
        sibling = sibling_map[current]
        # is_left_child[current] = True means WE are the left child
        # So sibling is to the RIGHT
        proof.append(MerkleProofStep(
            sibling_hash = sibling,
            is_left      = not is_left_child[current]  # sibling is left if WE are right
        ))
        current = child_to_parent[current]

    return proof   # O(log N)


def verify_merkle_proof(chunk_hash: str, proof: list[MerkleProofStep],
                        expected_root: str) -> bool:
    import hmac
    current = chunk_hash
    for step in proof:
        if step.is_left:
            # sibling is LEFT, current is RIGHT
            combined = bytes.fromhex(step.sibling_hash) + bytes.fromhex(current)
        else:
            # current is LEFT, sibling is RIGHT
            combined = bytes.fromhex(current) + bytes.fromhex(step.sibling_hash)
        current = hashlib.sha256(combined).hexdigest()
    return hmac.compare_digest(current, expected_root)
```

### Fix C — Streaming global Merkle root (for GB-scale files)

```python
def compute_global_merkle_root_streaming(
    file_path  : str,
    chunk_size : int,
) -> str:
    """
    Compute global Merkle root by streaming through file.
    Holds only chunk hashes in RAM (32 bytes each), not chunk data.
    For 10GB / 1200B = 8.7M chunks: 8.7M × 32B = 278MB RAM — acceptable.
    """
    chunk_hashes = []
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            if len(chunk) < chunk_size:
                chunk = chunk.ljust(chunk_size, b'\x00')
            chunk_hashes.append(hashlib.sha256(chunk).hexdigest())

    # Build tree from hashes only — no chunk data in RAM
    return _build_merkle_root_from_hashes(chunk_hashes)
```

---

## FIX 5 — Real RS Encoder (sender/m4_rs_encoder.py)

Replace fake duplication with real reedsolo:

```python
import reedsolo

def encode_with_rs(chunks: list[bytes], rs_config: RSConfig) -> list[bytes]:
    """
    Real Reed-Solomon encoding using reedsolo.RSCodec.

    RSCodec(nsym) takes nsym = number of PARITY symbols.
    nsym = rs_config.n - rs_config.k  (NOT rs_config.k directly)
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")

    chunk_size       = len(chunks[0])
    num_parity_syms  = rs_config.n - rs_config.k   # = num parity chunks
    codec            = reedsolo.RSCodec(num_parity_syms)

    parity_chunks = []
    for chunk in chunks:
        encoded      = codec.encode(chunk)
        parity_bytes = bytes(encoded[chunk_size:])
        # Pad parity to chunk_size so all chunks are equal length
        parity_chunk = parity_bytes.ljust(chunk_size, b'\x00')
        parity_chunks.append(parity_chunk)

    return list(chunks) + parity_chunks


def decode_with_rs(
    chunks_with_erasures : list[bytes | None],
    rs_config            : RSConfig,
    chunk_size           : int,
) -> list[bytes]:
    """
    Real RS recovery using reedsolo.
    Input:  K data chunks + parity chunks, some may be None
    Output: K data chunks with gaps filled, parity stripped
    """
    codec    = reedsolo.RSCodec(rs_config.n - rs_config.k)
    K        = len(chunks_with_erasures) - (rs_config.n - rs_config.k)
    erasures = [i for i, c in enumerate(chunks_with_erasures) if c is None]

    if len(erasures) > (rs_config.n - rs_config.k):
        raise ValueError(
            f"Too many erasures ({len(erasures)}) for parity ({rs_config.n - rs_config.k})"
        )

    filled  = [c if c is not None else bytes(chunk_size) for c in chunks_with_erasures]
    message = b"".join(filled)

    try:
        decoded, _, _ = codec.decode(message, erase_pos=erasures)
        return [decoded[i * chunk_size:(i + 1) * chunk_size] for i in range(K)]
    except reedsolo.ReedSolomonError as e:
        raise ValueError(f"RS decode failed: {e}") from e
```

---

## NEW MODULE — sender/m0_compress.py

```python
"""
sender/m0_compress.py — Streaming File Compression

Compresses input file with lz4 before it enters the pipeline.
Biggest single performance gain for text/log/CSV files (3-5× compression).
Streaming: never loads more than 64MB into RAM — safe for 10GB+ files.

Skip compression for already-compressed formats (jpg, mp4, zip, etc.)
to avoid wasting CPU and making them larger.
"""

import hashlib
import os
import lz4.frame
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SKIP_COMPRESSION_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
    '.mp4', '.mkv', '.avi', '.mov', '.wmv',
    '.zip', '.gz', '.bz2', '.7z', '.rar', '.lz4', '.zst',
    '.mp3', '.aac', '.flac', '.ogg',
    '.pdf',   # already internally compressed
}

BLOCK_SIZE = 64 * 1024 * 1024   # 64MB — fast, RAM-safe


@dataclass
class CompressionResult:
    compressed_path   : str
    original_size     : int
    compressed_size   : int
    compression_ratio : float    # original / compressed
    algorithm         : str      # "lz4" or "none"
    original_sha256   : str      # SHA-256 of original file (pre-compression)
    compressed_sha256 : str      # SHA-256 of compressed file (in-transit integrity)


def should_compress(file_path: str) -> bool:
    ext = Path(file_path).suffix.lower()
    return ext not in SKIP_COMPRESSION_EXTENSIONS


def compute_sha256_streaming(file_path: str) -> str:
    """Compute SHA-256 of any size file without loading it into RAM."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            block = f.read(65536)   # 64KB blocks
            if not block:
                break
            sha256.update(block)
    return sha256.hexdigest()


def compress_file(input_path: str, output_path: str) -> CompressionResult:
    """
    Compress file using lz4 streaming.
    If file type should not be compressed, copies as-is with algorithm="none".
    """
    original_size   = os.path.getsize(input_path)
    original_sha256 = compute_sha256_streaming(input_path)

    if not should_compress(input_path):
        # Copy as-is — no compression benefit
        import shutil
        shutil.copy2(input_path, output_path)
        compressed_sha256 = original_sha256
        return CompressionResult(
            compressed_path   = output_path,
            original_size     = original_size,
            compressed_size   = original_size,
            compression_ratio = 1.0,
            algorithm         = "none",
            original_sha256   = original_sha256,
            compressed_sha256 = compressed_sha256,
        )

    # lz4 streaming compression — 64MB blocks
    with open(input_path, 'rb') as f_in, \
         lz4.frame.open(output_path, 'wb') as f_out:
        while True:
            block = f_in.read(BLOCK_SIZE)
            if not block:
                break
            f_out.write(block)

    compressed_size   = os.path.getsize(output_path)
    compressed_sha256 = compute_sha256_streaming(output_path)
    ratio             = original_size / max(compressed_size, 1)

    logger.info(
        f"Compressed: {original_size / 1024**2:.1f}MB → "
        f"{compressed_size / 1024**2:.1f}MB ({ratio:.1f}× ratio)"
    )

    return CompressionResult(
        compressed_path   = output_path,
        original_size     = original_size,
        compressed_size   = compressed_size,
        compression_ratio = ratio,
        algorithm         = "lz4",
        original_sha256   = original_sha256,
        compressed_sha256 = compressed_sha256,
    )
```

---

## NEW MODULE — receiver/m24_decompress.py

```python
"""
receiver/m24_decompress.py — Streaming Decompression

Decompresses lz4 file after all integrity checks pass.
Streaming: safe for 10GB+ files. Never loads whole file into RAM.
Verifies decompressed result against original_sha256 from manifest.
"""

import hashlib
import hmac
import lz4.frame
import logging
import os

logger = logging.getLogger(__name__)

BLOCK_SIZE = 64 * 1024 * 1024   # 64MB read blocks


def decompress_file(
    compressed_path : str,
    output_path     : str,
    algorithm       : str,    # manifest.compression_algorithm
    expected_sha256 : str,    # manifest.original_sha256
) -> bool:
    """
    Decompress and verify.
    Returns True on success. Returns False (never raises) on any failure.
    """
    if algorithm == "none":
        import shutil
        shutil.copy2(compressed_path, output_path)
        actual = _sha256_streaming(output_path)
        if not hmac.compare_digest(actual, expected_sha256):
            logger.error("SHA-256 mismatch on uncompressed file")
            return False
        return True

    if algorithm != "lz4":
        logger.error(f"Unknown compression algorithm: {algorithm}")
        return False

    sha256 = hashlib.sha256()
    try:
        with lz4.frame.open(compressed_path, 'rb') as f_in, \
             open(output_path, 'wb') as f_out:
            while True:
                block = f_in.read(BLOCK_SIZE)
                if not block:
                    break
                f_out.write(block)
                sha256.update(block)
    except Exception as e:
        logger.error(f"Decompression failed: {e}")
        return False

    actual = sha256.hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        logger.error("Decompressed SHA-256 mismatch — file corrupted in transit")
        return False

    os.remove(compressed_path)
    logger.info(f"Decompressed and verified: {output_path}")
    return True


def _sha256_streaming(path: str) -> str:
    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            block = f.read(65536)
            if not block:
                break
            sha256.update(block)
    return sha256.hexdigest()
```

---

## UPDATED PROFILES (sender/m5_profile.py)

MAX_PASSES = 2 enforced everywhere. Performance-tuned for real usage.

```python
@dataclass(frozen=True)
class Profile:
    passes          : int
    overhead_ratio  : float
    rs_config       : str
    interleave_depth: int
    header_redundancy: int
    window_size_bytes: int

    def __post_init__(self):
        if not (1 <= self.passes <= 2):              # ← hard cap at 2
            raise ValueError(f"passes must be 1–2, got {self.passes}")
        if not (0.10 <= self.overhead_ratio <= 0.30):
            raise ValueError(f"overhead_ratio out of range: {self.overhead_ratio}")


PROFILES = {
    # Small files (< 10MB) — single window, full checks
    ("small", "standard"):    Profile(passes=1, overhead_ratio=0.25,
        rs_config="RS(16,2)", interleave_depth=2, header_redundancy=3,
        window_size_bytes=16 * 1024 * 1024),
    ("small", "critical"):    Profile(passes=2, overhead_ratio=0.25,
        rs_config="RS(16,4)", interleave_depth=3, header_redundancy=5,
        window_size_bytes=16 * 1024 * 1024),
    ("small", "classified"):  Profile(passes=2, overhead_ratio=0.30,
        rs_config="RS(32,8)", interleave_depth=4, header_redundancy=5,
        window_size_bytes=16 * 1024 * 1024),

    # Medium files (10MB–1GB) — balanced
    ("medium", "standard"):   Profile(passes=1, overhead_ratio=0.20,
        rs_config="RS(32,4)", interleave_depth=3, header_redundancy=3,
        window_size_bytes=64 * 1024 * 1024),
    ("medium", "critical"):   Profile(passes=2, overhead_ratio=0.20,
        rs_config="RS(32,6)", interleave_depth=4, header_redundancy=5,
        window_size_bytes=64 * 1024 * 1024),
    ("medium", "classified"): Profile(passes=2, overhead_ratio=0.25,
        rs_config="RS(32,8)", interleave_depth=5, header_redundancy=5,
        window_size_bytes=64 * 1024 * 1024),

    # Large files (>1GB) — performance priority, large windows
    ("large", "standard"):    Profile(passes=1, overhead_ratio=0.15,
        rs_config="RS(64,4)", interleave_depth=4, header_redundancy=3,
        window_size_bytes=128 * 1024 * 1024),
    ("large", "critical"):    Profile(passes=2, overhead_ratio=0.15,
        rs_config="RS(64,6)", interleave_depth=6, header_redundancy=5,
        window_size_bytes=128 * 1024 * 1024),
    ("large", "classified"):  Profile(passes=2, overhead_ratio=0.20,
        rs_config="RS(64,8)", interleave_depth=8, header_redundancy=5,
        window_size_bytes=128 * 1024 * 1024),
}
```

---

## UPDATED WINDOWING (sender/m1_windowing.py)

Window size is proportional to file size. Small files = single window.

```python
def get_window_size_for_file(file_size_bytes: int, profile: Profile) -> int:
    """
    Proportional window sizing — avoids windowing overhead for small files.

    < 64MB   → single window (no split at all)
    64MB–1GB → 64MB windows (profile default for medium)
    1GB–10GB → 128MB windows (profile default for large)
    > 10GB   → 256MB windows (only if sufficient RAM)
    """
    ONE_MB = 1024 * 1024
    ONE_GB = 1024 * ONE_MB

    if file_size_bytes < 64 * ONE_MB:
        return file_size_bytes      # single window, zero split overhead

    if file_size_bytes < ONE_GB:
        return 64 * ONE_MB

    if file_size_bytes < 10 * ONE_GB:
        return 128 * ONE_MB

    return 256 * ONE_MB             # > 10GB — requires high-RAM system
```

---

## STREAMING SENDER PIPELINE (sender/pipeline.py)

**Critical for GB scale.** Process and transmit one window at a time.
Never hold more than one window's packets in RAM simultaneously.

```python
def run_sender(file_path: str, remote_addr: tuple, criticality: str = "standard") -> None:
    """
    Streaming sender pipeline.
    Memory footprint: ~200MB peak (one window at a time).
    Works for any file size.
    """
    import tempfile, os, time
    from pathlib import Path

    logger.info(f"Transfer start: {file_path} → {remote_addr}")
    total_start = time.time()

    # Step 1: Get profile
    file_size = os.path.getsize(file_path)
    profile   = get_profile(file_size, criticality)

    # Step 2: Compress (streaming — never loads whole file)
    with tempfile.NamedTemporaryFile(suffix='.lz4', delete=False) as tmp:
        compressed_path = tmp.name

    compress_result = compress_file(file_path, compressed_path)
    compressed_size = compress_result.compressed_size
    logger.info(f"Compressed {file_size / 1024**2:.1f}MB → "
                f"{compressed_size / 1024**2:.1f}MB "
                f"({compress_result.compression_ratio:.1f}×)")

    # Step 3: Window sizing
    window_size = get_window_size_for_file(compressed_size, profile)
    windows     = compute_windows(compressed_size, window_size)

    # Step 4: Streaming Merkle root (hashes only, no chunk data in RAM)
    merkle_root = compute_global_merkle_root_streaming(compressed_path, DEFAULT_CHUNK_SIZE)

    # Step 5: Generate manifest
    transfer_id = str(uuid.uuid4())
    manifest = TransferManifest(
        transfer_id           = transfer_id,
        file_name             = os.path.basename(file_path),
        file_size             = compressed_size,
        file_sha256           = compress_result.compressed_sha256,
        original_size         = compress_result.original_size,
        original_sha256       = compress_result.original_sha256,
        compression_algorithm = compress_result.algorithm,
        chunk_size            = DEFAULT_CHUNK_SIZE,
        total_chunks          = compute_chunk_count(compressed_size, DEFAULT_CHUNK_SIZE),
        total_windows         = len(windows),
        merkle_root           = merkle_root,
        rs_n                  = profile.rs_n,
        rs_k                  = profile.rs_k,
        num_passes            = profile.passes,
        overhead_ratio        = profile.overhead_ratio,
        interleave_depth      = profile.interleave_depth,
        window_size_bytes     = window_size,
        # ... remaining manifest fields
    )

    # Step 6: Transmit manifest with redundancy
    manifest_bytes = serializer.serialize_manifest(manifest)
    for _ in range(profile.header_redundancy):
        transmitter._send_raw(remote_addr, manifest_bytes)

    # Step 7: Process and transmit windows ONE AT A TIME
    for window in windows:
        t0 = time.time()

        # Read only this window from disk
        window_data = get_file_window(Path(compressed_path), window)

        # Chunk
        chunk_result = chunk_window(window_data, DEFAULT_CHUNK_SIZE)

        # RS encode
        chunks_with_rs = encode_with_rs(chunk_result.chunks, parse_rs_config(profile.rs_config))

        # Fountain encode — all passes
        all_packets = []
        for pass_id in range(profile.passes):
            seed    = seed_for_pass(transfer_id, window.window_id, pass_id)
            packets = encoder.encode(chunks_with_rs, seed=seed,
                                     overhead_ratio=profile.overhead_ratio)
            for p in packets:
                p.pass_id = pass_id
            all_packets.extend(packets)

        # Interleave
        transmitted = interleave_encoded_packets(all_packets, profile.interleave_depth)

        # Transmit immediately
        for packet in transmitted:
            packet_bytes = serializer.serialize_packet(packet)
            transmitter._send_raw(remote_addr, packet_bytes)

        # FREE MEMORY — critical for GB scale
        del window_data, chunk_result, chunks_with_rs, all_packets, transmitted

        elapsed = time.time() - t0
        pct     = (window.window_id + 1) / len(windows) * 100
        logger.info(f"Window {window.window_id + 1}/{len(windows)} "
                   f"({pct:.1f}%) sent in {elapsed:.1f}s")

    # Footer
    footer = f"TRANSFER_END:{transfer_id}".encode()
    for _ in range(3):
        transmitter._send_raw(remote_addr, footer)

    os.remove(compressed_path)
    total_elapsed = time.time() - total_start
    logger.info(f"Transfer complete: {total_elapsed:.1f}s total")
```

---

## STREAMING RECEIVER PIPELINE (receiver/pipeline.py)

Write each decoded window to disk immediately. Never buffer all windows in RAM.

```python
def run_receiver(bind_addr: str, bind_port: int, output_dir: str) -> None:
    """
    Streaming receiver pipeline.
    Memory footprint: ~200MB peak (one decode window at a time).
    Window temp files written to disk as each window completes.
    """
    import tempfile, os, psutil

    quarantine_dir = Path(output_dir) / "quarantine"
    windows_dir    = Path(output_dir) / "windows_tmp"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    windows_dir.mkdir(parents=True, exist_ok=True)

    manifest     : TransferManifest | None = None
    window_files : dict[int, Path]         = {}   # window_id → temp file path
    active_pools : dict[int, list]         = {}   # window_id → packet list

    while True:
        raw = receiver.receive_nonblocking()
        if raw is None:
            _check_pool_timeouts(active_pools, manifest, ...)
            continue

        # Validate + deserialize
        packet = _validate_and_parse(raw.payload, manifest)
        if packet is None:
            continue

        # Manifest packet?
        if isinstance(packet, TransferManifest):
            manifest = packet
            logger.info(f"Manifest: {manifest.file_name}, "
                       f"{manifest.total_windows} windows")
            continue

        if manifest is None:
            continue   # data before manifest — ignore

        # Pool packet
        pooler.add_packet(manifest.transfer_id, packet.window_id, packet)

        # Check readiness
        K_prime = _compute_K_prime(manifest, packet.window_id)
        if pooler.is_ready_to_decode(manifest.transfer_id, packet.window_id, K_prime):
            _decode_window_to_disk(
                manifest, packet.window_id, K_prime,
                windows_dir, window_files
            )

        # All windows done?
        if len(window_files) == manifest.total_windows:
            _assemble_and_finish(manifest, window_files, quarantine_dir, output_dir)
            break


def _decode_window_to_disk(manifest, window_id, K_prime, windows_dir, window_files):
    """Decode one window, verify, write to disk, free RAM."""
    import psutil

    # Memory budget check before allocating Tanner graph
    available_mb = psutil.virtual_memory().available / 1024**2
    estimated_mb = (K_prime * manifest.chunk_size * 2) / 1024**2
    if estimated_mb > available_mb * 0.80:
        logger.error(f"Insufficient RAM for window {window_id}: "
                    f"need ~{estimated_mb:.0f}MB, have {available_mb:.0f}MB")
        window_files[window_id] = None
        return

    pool = pooler.get_unified_pool(manifest.transfer_id, window_id)

    # Fountain decode
    decode_result = fountain_decoder.decode_window(pool, K_prime, manifest.chunk_size)

    # RS recovery
    recovered = rs_decoder.recover(decode_result.chunks, manifest.rs_config,
                                   manifest.chunk_size)

    # Merkle verify
    verified = merkle_verifier.verify_all(recovered, manifest, window_id)
    if not verified.all_passed:
        logger.error(f"Window {window_id} Merkle failure")
        window_files[window_id] = None
        return

    # Reassemble
    window_bytes = window_reassembler.reassemble(verified.chunks, manifest, window_id)

    # Write to disk immediately — FREE RAM
    temp_path = windows_dir / f"window_{window_id:06d}.bin"
    temp_path.write_bytes(window_bytes)
    window_files[window_id] = temp_path

    del pool, decode_result, recovered, verified, window_bytes

    pooler.clear_window(manifest.transfer_id, window_id)

    done = len(window_files)
    total = manifest.total_windows
    logger.info(f"Window {window_id + 1}/{total} stored "
               f"({done/total*100:.1f}% complete)")


def _assemble_and_finish(manifest, window_files, quarantine_dir, output_dir):
    """Concatenate window files → final file. Streaming, 64MB blocks."""
    import hmac, hashlib

    output_path = quarantine_dir / manifest.file_name
    sha256      = hashlib.sha256()
    READ_BLOCK  = 64 * 1024 * 1024

    with open(output_path, 'wb') as out:
        for window_id in range(manifest.total_windows):
            path = window_files.get(window_id)
            if path is None:
                logger.error(f"Window {window_id} failed — transfer incomplete")
                return
            with open(path, 'rb') as wf:
                while True:
                    block = wf.read(READ_BLOCK)
                    if not block:
                        break
                    out.write(block)
                    sha256.update(block)
            path.unlink()   # delete temp file after use

    actual = sha256.hexdigest()
    if not hmac.compare_digest(actual, manifest.file_sha256):
        logger.error("SHA-256 mismatch on assembled file")
        return

    # Decompress
    final_path = Path(output_dir) / manifest.file_name
    success = decompress_file(
        compressed_path = str(output_path),
        output_path     = str(final_path),
        algorithm       = manifest.compression_algorithm,
        expected_sha256 = manifest.original_sha256,
    )

    if success:
        logger.info(f"Transfer complete: {final_path}")
    else:
        logger.error("Decompression or final verification failed")
```

---

## FIXES FOR EXISTING MODULES

### m6_fountain_encoder.py

```python
# Fix import paths (remove data_diode. prefix)
from fountain.interface import get_encoder, EncodedPacket
from sender.m7_multipass import seed_for_pass

# Fix return type (.packets does not exist — encode() returns list directly)
encoded_packets = encoder.encode(chunks, seed=seed, overhead_ratio=overhead_ratio)
for p in encoded_packets:
    p.pass_id = pass_id
all_packets.extend(encoded_packets)

# Fix codec hardcoding — accept as parameter
def encode_window_multipass(..., codec: str = "lt") -> list[EncodedPacket]:
    encoder = get_encoder(codec)
```

### m8_interleaver.py

```python
# Skip empty passes instead of raising
for pass_id, packets in enumerate(packets_by_pass):
    if not packets:
        continue   # skip silently

# Accept EncodedPacket directly for cleaner pipeline
def interleave_encoded_packets(
    packets_by_pass: list[list[EncodedPacket]],
    stride: int
) -> list[EncodedPacket]:
    ...
    return flat_list_of_encoded_packets   # not (pass_id, packet_id) tuples
```

### m9_metadata.py

```python
# crcmod at module level (not inside every function)
import crcmod
_CRC32C = crcmod.mkCrcFun(0x11EDC6F41, rev=True, initCrc=0xffffffff, xorOut=0xffffffff)

# MAC covers metadata + payload (not payload alone)
mac_input = serialize_metadata_fields(metadata) + payload
blake3_mac = compute_blake3_mac(mac_input, shared_secret)

# Timing-safe comparison
import hmac
return hmac.compare_digest(mac, expected)
```

### m10_serializer.py

```python
# crcmod at module level
import crcmod
_CRC32C = crcmod.mkCrcFun(0x11EDC6F41, rev=True, initCrc=0xffffffff, xorOut=0xffffffff)

# Add missing packet serialization — critical, transmitter needs this
def serialize_packet(packet: EncodedPacket) -> bytes:
    """Serialize EncodedPacket to bytes for UDP transmission."""
    packet_dict = {
        "packet_id"          : packet.packet_id,
        "pass_id"            : packet.pass_id,
        "seed"               : packet.seed,
        "degree"             : packet.degree,
        "chunk_ids"          : packet.chunk_ids,
        "source_chunk_count" : packet.source_chunk_count,
        "data"               : packet.data.hex(),
    }
    json_bytes = json.dumps(packet_dict).encode("utf-8")
    frame = BytesIO()
    frame.write(struct.pack("B", PACKET_VERSION))
    frame.write(struct.pack(">I", len(json_bytes)))
    frame.write(json_bytes)
    crc = _CRC32C(frame.getvalue())
    frame.write(struct.pack(">I", crc))
    return frame.getvalue()

def deserialize_packet(data: bytes) -> EncodedPacket | None:
    """Deserialize packet bytes. Returns None on any error (caller logs)."""
    try:
        f       = BytesIO(data)
        version = struct.unpack("B", f.read(1))[0]
        if version != PACKET_VERSION:
            return None
        length     = struct.unpack(">I", f.read(4))[0]
        json_bytes = f.read(length)
        crc_exp    = struct.unpack(">I", data[-4:])[0]
        crc_act    = _CRC32C(data[:-4])
        if crc_act != crc_exp:
            return None
        d = json.loads(json_bytes.decode("utf-8"))
        return EncodedPacket(
            packet_id          = d["packet_id"],
            pass_id            = d["pass_id"],
            seed               = d["seed"],
            degree             = d["degree"],
            chunk_ids          = d["chunk_ids"],
            data               = bytes.fromhex(d["data"]),
            source_chunk_count = d["source_chunk_count"],
        )
    except Exception:
        return None
```

### m13_validator.py — Add missing hard limits

```python
import psutil

# Add to ManifestValidator:
MAX_K               = 1_000_000
MAX_TRANSFER_SIZE   = 100 * 1024**3
MAX_PASSES          = 2              # ← updated from 3
MAX_WINDOWS         = 10_000
MAX_RS_PARITY       = 128

def validate_manifest_hard_limits(self, manifest: TransferManifest) -> ValidationError:
    if manifest.total_chunks > MAX_K:
        return ValidationError(False, f"total_chunks {manifest.total_chunks} > MAX_K {MAX_K}")
    if manifest.file_size > MAX_TRANSFER_SIZE:
        return ValidationError(False, f"file_size exceeds 100GB limit")
    if manifest.num_passes > MAX_PASSES:
        return ValidationError(False, f"num_passes {manifest.num_passes} > {MAX_PASSES}")
    if manifest.total_windows > MAX_WINDOWS:
        return ValidationError(False, f"total_windows {manifest.total_windows} > {MAX_WINDOWS}")
    if (manifest.rs_n - manifest.rs_k) > MAX_RS_PARITY:
        return ValidationError(False, f"RS parity exceeds limit")
    return ValidationError(True)

# Add timestamp replay check:
def validate_timestamp(self, timestamp: float, transfer_start: float,
                        max_duration: float = 3600) -> ValidationError:
    now = time.time()
    if timestamp < transfer_start - 60:
        return ValidationError(False, "REPLAY: timestamp too old")
    if timestamp > transfer_start + max_duration:
        return ValidationError(False, "REPLAY: timestamp too far in future")
    return ValidationError(True)
```

### m15_pooler.py — Key fixes

```python
# Store EncodedPacket directly (not PooledPacket)
# TTL based on last_activity, not oldest packet
# Add is_ready_to_decode() trigger
# Add pool size cap

def add_packet(self, transfer_id, window_id, packet: EncodedPacket) -> bool:
    dedup_key = (window_id, packet.pass_id, packet.packet_id)
    if dedup_key in self.dedup_sets[transfer_id]:
        return False
    self.pools[transfer_id][window_id][dedup_key] = packet
    self.dedup_sets[transfer_id].add(dedup_key)
    self.last_activity[transfer_id] = time.time()   # activity-based TTL
    return True

def is_ready_to_decode(self, transfer_id, window_id, K_prime) -> bool:
    count = self.get_packet_count(transfer_id, window_id)
    if count >= int(K_prime * 1.05):
        return True
    idle = time.time() - self.last_activity.get(transfer_id, time.time())
    return idle > WINDOW_TIMEOUT   # timeout forces decode with what we have

def get_unified_pool(self, transfer_id, window_id) -> list[EncodedPacket]:
    return list(self.pools[transfer_id][window_id].values())
```

### m16_fountain_decoder.py — Critical fix

```python
# Decode ALL passes as ONE unified pool — NOT per-pass separately
def decode_window(self, pooled_packets: list[EncodedPacket],
                  K_prime: int, chunk_size: int) -> DecodeResult:
    """
    CRITICAL: pool is already unified (all passes combined by m15_pooler).
    One decode call. Cross-pass recovery happens inside the Tanner graph.
    Never decode passes separately and merge — that loses cross-pass benefit.
    """
    if not pooled_packets:
        return DecodeResult(chunks=[None]*K_prime, success=False,
                           recovered_count=0, missing_ids=list(range(K_prime)),
                           packets_used=0)
    return self.decoder.decode(pooled_packets, K_prime=K_prime)
```

### m18_merkle_verifier.py — Real verification

```python
# Replace leaf-lookup stub with real proof path traversal
def verify_chunk_merkle(chunk_data, chunk_id, merkle_root, tree_data) -> bool:
    chunk_hash = hashlib.sha256(chunk_data).hexdigest()
    proof      = get_merkle_proof(tree_data, chunk_id, ...)
    return verify_merkle_proof(chunk_hash, proof, merkle_root)
    # Never return True when tree data is missing — return False and log
```

### m21_verifier.py — Streaming SHA-256 + real Merkle

```python
# Streaming SHA-256 (never loads whole file)
@staticmethod
def verify_sha256_streaming(file_path: str, expected_hash: str) -> bool:
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            block = f.read(65536)
            if not block: break
            sha256.update(block)
    return hmac.compare_digest(sha256.hexdigest(), expected_hash)

# Real Merkle root check (not placeholder)
@staticmethod
def verify_merkle_root(window_merkle_roots: list[str], expected_root: str) -> bool:
    computed_root = build_merkle_root_from_hashes(window_merkle_roots)
    return hmac.compare_digest(computed_root, expected_root)
```

### tests/test_chunker.py — Two bug fixes

```python
# Fix 1: LossScenario has no 'name' field in common/models.py
# Import from loss_simulator instead, or remove name field from test
from tests.utils.loss_simulator import LossScenario as SimLossScenario
scenario = SimLossScenario(random_loss_rate=0.10)

# Fix 2: classified profile uses ("any", "classified") key — not size-based
def test_get_profile_classified_any_size(self):
    for size in [1_000, 100_000_000, 5_000_000_000]:
        profile = get_profile(size, "classified")
        assert profile.passes >= 1
```

### tests/test_fountain.py — Three fixes

```python
# Fix 1: add chunk_ids to reproducibility check
assert p1.chunk_ids == p2.chunk_ids

# Fix 2: empty pool returns graceful result, not ValueError
result = decoder.decode([], K_prime=50)
assert not result.success
assert all(c is None for c in result.chunks)

# Fix 3: set pass_id in multi-pass test
for pass_id in range(2):   # 2 passes not 3
    encoded = encoder.encode(chunks, seed=pass_id*1000, overhead_ratio=0.5)
    for p in encoded:
        p.pass_id = pass_id
    all_encoded.extend(encoded)
```

### tests/utils/loss_simulator.py — Thread safety fix

```python
# Replace all global random.seed() with random.Random() instances
def apply_random_loss(packets, loss_rate, seed=None):
    rng = random.Random(seed)   # instance, not global
    return [None if rng.random() < loss_rate else p for p in packets], [...]
```

---

## MANIFEST ADDITIONS (common/models.py)

Add compression fields to TransferManifest:

```python
@dataclass
class TransferManifest:
    # ... all existing fields unchanged ...
    
    # NEW: compression fields
    compression_algorithm : str    # "lz4" or "none"
    original_size         : int    # bytes before compression
    original_sha256       : str    # SHA-256 of original file (pre-compression)
    # Note: file_size and file_sha256 refer to COMPRESSED bytes (in-transit)
```

Add progress tracking dataclass:

```python
@dataclass
class TransferProgress:
    """Real-time progress for large file transfers."""
    transfer_id       : str
    file_name         : str
    total_windows     : int
    completed_windows : int   = 0
    total_packets     : int   = 0
    start_time        : float = field(default_factory=time.time)

    @property
    def percent_complete(self) -> float:
        return (self.completed_windows / self.total_windows * 100
                if self.total_windows else 0.0)

    @property
    def eta_seconds(self) -> float:
        if self.completed_windows == 0:
            return float('inf')
        rate = self.completed_windows / max(time.time() - self.start_time, 0.001)
        return (self.total_windows - self.completed_windows) / rate

    def log(self) -> None:
        eta = self.eta_seconds
        eta_str = (f"{eta/60:.1f}min" if eta < 3600 else f"{eta/3600:.1f}hr"
                   if eta != float('inf') else "unknown")
        logger.info(
            f"[{self.transfer_id[:8]}] {self.percent_complete:.1f}% | "
            f"Window {self.completed_windows}/{self.total_windows} | "
            f"ETA: {eta_str} | Packets: {self.total_packets:,}"
        )
```

---

## IMPLEMENTATION ORDER

Apply in this exact sequence. Each step unblocks the next. Run tests
after each group before proceeding.

```
GROUP 1 — Core correctness (do this first, everything else depends on it)
─────────────────────────────────────────────────────────────────────────
 1.  fountain/interface.py     Expand EncodedPacket + add list_encoders/decoders
 2.  fountain/lt_encoder.py    numpy XOR + random.Random + correct RS + chunk_ids
 3.  fountain/lt_decoder.py    Read chunk_ids + numpy XOR + set.discard + graceful empty
     → pytest tests/test_fountain.py   (ALL must pass)

 4.  sender/m3_merkle.py       O(1) proof + correct left/right + streaming global root
     → pytest tests/test_merkle.py

 5.  sender/m4_rs_encoder.py   Real reedsolo encode + decode
     → pytest tests/test_rs.py

 6.  sender/m10_serializer.py  Add serialize_packet/deserialize_packet + crcmod module-level
     → pytest tests/test_manifest.py

GROUP 2 — Compression (biggest single performance gain)
─────────────────────────────────────────────────────────────────────────
 7.  sender/m0_compress.py     NEW: streaming lz4 compression
     receiver/m24_decompress.py NEW: streaming lz4 decompression
     common/models.py           Add compression fields to TransferManifest
     sender/m0_manifest.py      Include compression fields
     → pytest tests/test_compress.py   (new test file)

GROUP 3 — Pipeline fixes (wiring correctness)
─────────────────────────────────────────────────────────────────────────
 8.  sender/m6_fountain_encoder.py  Fix imports + return type + codec param
 9.  sender/m8_interleaver.py       Skip empty passes + return EncodedPacket
 10. sender/m9_metadata.py          crcmod module-level + hmac.compare_digest + full MAC
 11. sender/m11_transmitter.py      send_transfer() + sleep-based rate control
 12. receiver/m12_receiver.py       Per-transfer buffers + correct max_packet_size
 13. receiver/m13_validator.py      All hard limits + timestamp replay + memory budget
 14. receiver/m15_pooler.py         EncodedPacket storage + readiness trigger + activity TTL
 15. receiver/m16_fountain_decoder  Unified pool decode + correct signature
 16. receiver/m17_rs_decoder.py     Real reedsolo decode
 17. receiver/m18_merkle_verifier   Real proof traversal + use models.py types
 18. receiver/m21_verifier.py       Streaming SHA-256 + real Merkle root
     → pytest tests/test_validator.py tests/test_pooler.py

GROUP 4 — Streaming pipeline (GB-scale support)
─────────────────────────────────────────────────────────────────────────
 19. sender/m1_windowing.py         Proportional window sizing
 20. sender/pipeline.py             REWRITE: streaming one-window-at-a-time
 21. receiver/m20_file_reassembler  REWRITE: disk-based streaming assembly
 22. receiver/pipeline.py           REWRITE: streaming disk-backed + progress logging
 23. common/models.py               Add TransferProgress dataclass
     → pytest tests/test_pipeline_e2e.py   (small file: < 30s, 30MB: < 2min)

GROUP 5 — Test fixes
─────────────────────────────────────────────────────────────────────────
 24. tests/test_chunker.py          Fix LossScenario field + classified key
 25. tests/test_fountain.py         chunk_ids check + empty pool + pass_id in multi-pass
 26. tests/utils/loss_simulator.py  random.Random instances + burst stat fix
     → pytest tests/   (full suite must pass)

GROUP 6 — Large file validation
─────────────────────────────────────────────────────────────────────────
 27. tests/test_pipeline_e2e.py     Add 100MB, 500MB, 1GB test cases
     → pytest tests/test_pipeline_e2e.py --timeout=600
     → Verify memory stays < 600MB throughout (use psutil in test)
     → Verify progress logs appear every window
```

---

## PERFORMANCE TARGETS

After all fixes applied:

```
File Size    Type         Compression  Windows  Est. Time (Codespaces)
──────────────────────────────────────────────────────────────────────
30 MB        text         ~8 MB        1        < 30 seconds
100 MB       text         ~25 MB       1        < 90 seconds
500 MB       text         ~125 MB      2        < 7 minutes
500 MB       video        ~470 MB      8        < 20 minutes
1 GB         text         ~250 MB      4        < 12 minutes
2 GB         text         ~500 MB      8        < 25 minutes
2 GB         binary       ~1.8 GB      15       < 60 minutes
10 GB        text         ~2.5 GB      20       < 2.5 hours
10 GB        video        ~9.5 GB      75       < 8 hours

Assumptions: 1 pass standard criticality, 10,000 pps TX rate,
             numpy XOR active, Codespaces 2 CPU / 8GB RAM.
For critical (2 passes): multiply by ~2×.
```

**If 30MB still exceeds 2 minutes after all fixes, profile first:**
```bash
python -m cProfile -s cumulative simulate_diode.py \
    --file test_30mb.txt --criticality standard 2>&1 | head -40
```
The top function by cumulative time will show the remaining bottleneck.

---

## MEMORY TARGETS

```
File Size    Peak RAM (sender)    Peak RAM (receiver)
──────────────────────────────────────────────────────
30 MB        < 200 MB             < 200 MB
1 GB         < 300 MB             < 300 MB
10 GB        < 400 MB             < 400 MB

If RAM exceeds these targets, the streaming pipeline has a memory leak.
Check: del statements after each window in both pipelines.
Use: watch -n1 "ps aux | grep python" to monitor during a large transfer.
```

---

## KEY INVARIANTS — NEVER VIOLATE

```
 1. Receiver never sends. recvfrom() only. No exceptions.
 2. IFountainEncoder/IFountainDecoder are the only interfaces to codec logic.
 3. Manifest transmitted before ANY data packets.
 4. Decoder hard limits checked BEFORE any graph memory allocated.
 5. No file reaches secure storage without: CRC32C → BLAKE3-MAC → Ed25519 →
    fountain decode → RS decode → Merkle per-chunk → SHA-256 + Merkle root →
    quarantine → decompress verify.
 6. All chunks equal size. Last chunk zero-padded. Receiver strips padding.
 7. Different passes use different seeds: hash(transfer_id:window_id:pass_id).
 8. MAX_PASSES = 2. Never 3.
 9. Sender holds max ONE window in RAM at a time. del after transmit.
10. Receiver writes each decoded window to disk immediately. del after write.
11. File assembly streams from window temp files — never loads whole file.
12. SHA-256 always computed streaming (64KB blocks). Never open().read().
13. Compression always streaming (lz4.frame not lz4.block). 64MB blocks max.
14. Memory budget checked via psutil before Tanner graph allocation.
15. random.Random(seed) instances everywhere. Never random.seed() global.
16. hmac.compare_digest() for ALL hash/MAC comparisons. Never == on secrets.
17. crcmod CRC function initialised ONCE at module level. Never inside loops.
```