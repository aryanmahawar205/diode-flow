# Data Diode — Updated Build Prompt (Performance & Architecture Revision)
# =============================================================================
# This is the REVISED prompt. It supersedes the previous version.
# Key changes from original:
#   1. Compression module added (M0_pre) — biggest single performance gain
#   2. numpy-based XOR throughout fountain codec — fixes core slowdown
#   3. EncodedPacket expanded with chunk_ids, packet_id, pass_id (critical bug fix)
#   4. Passes capped at 2 across all profiles
#   5. Window sizing made proportional to file size
#   6. Profiles simplified and performance-tuned
#   7. random.Random instances used everywhere (thread safety + correctness)
#   8. RS encoder uses real reedsolo (not fake duplication)
#   9. Merkle proof search uses reverse lookup (O(1) not O(N))
#  10. Decoder returns graceful DecodeResult on empty pool (not ValueError)
# =============================================================================

---

## CONTEXT — WHAT HAS BEEN BUILT AND WHAT NEEDS FIXING

The following modules exist but have bugs that cause severe slowdown on files
larger than ~5MB. Do NOT rewrite from scratch. Fix the specific issues listed
per module. New modules are clearly marked NEW.

### Performance Root Causes (fix these first, in order)

```
Priority 1 — numpy XOR in LT encoder/decoder
  Current: byte-by-byte Python loop over 1200-byte chunks
  Fix: numpy XOR — 100x faster, single line
  Impact: Fixes ~80% of the slowdown

Priority 2 — EncodedPacket missing chunk_ids field
  Current: decoder re-derives chunk selections by re-running PRNG
  Fix: store chunk_ids in EncodedPacket, decoder reads directly
  Impact: Fixes incorrect decode results + eliminates redundant PRNG work

Priority 3 — Global random.seed() instead of random.Random instances
  Current: random.seed(x) sets global state, non-deterministic under any
           concurrent usage
  Fix: rng = random.Random(seed), pass rng through encode loop
  Impact: Fixes correctness, makes tests reproducible

Priority 4 — Compression added before chunking
  Current: raw file bytes go straight to chunker
  Fix: compress with lz4 first, decompress after file reassembly
  Impact: 30MB text file → ~6MB before encoding → 5x fewer chunks/packets

Priority 5 — Merkle O(N) parent scan
  Current: get_merkle_proof() scans entire tree dict at every level
  Fix: build reverse lookup dict once: child_hash → parent_node
  Impact: Fixes proof generation from O(N log N) to O(log N)
```

---

## WHAT YOU ARE BUILDING

A **software-only Data Diode system** implemented in Python.

A data diode enforces **strictly one-way communication** — data flows from
sender to receiver, and absolutely nothing flows back. This is a core security
primitive used in critical infrastructure, defense, and classified environments.

**Phase scope:** Software only. Simulated as two Python processes over UDP
loopback (127.0.0.1). The one-way constraint is enforced at the application
level — the receiver process never opens an outbound socket under any
circumstances.

**Language:** Python 3.11+
**Environment:** GitHub Codespaces (Ubuntu)
**Testing:** pytest, module-by-module

---

## UPDATED FILE STRUCTURE

```
data_diode/
│
├── common/
│   ├── __init__.py
│   ├── config.py              # Updated: new profiles, compression settings
│   ├── models.py              # Updated: EncodedPacket expanded
│   └── proto/
│       ├── manifest.proto
│       ├── packet.proto
│       └── generated/
│
├── fountain/
│   ├── __init__.py
│   ├── interface.py           # Updated: EncodedPacket gets chunk_ids, packet_id, pass_id
│   ├── lt_encoder.py          # FIXED: numpy XOR, random.Random instances, correct RS
│   ├── lt_decoder.py          # FIXED: reads chunk_ids directly, numpy XOR, O(1) graph
│   └── raptorq_stub.py        # Unchanged
│
├── sender/
│   ├── __init__.py
│   ├── m0_compress.py         # NEW: compress file before transfer (lz4/zstd)
│   ├── m0_manifest.py         # Updated: includes compression metadata
│   ├── m1_windowing.py        # Updated: proportional window sizing
│   ├── m2_chunker.py          # Unchanged (correct)
│   ├── m3_merkle.py           # FIXED: O(1) proof generation via reverse lookup
│   ├── m4_rs_encoder.py       # FIXED: real reedsolo, not fake duplication
│   ├── m5_profile.py          # Updated: max 2 passes, performance-tuned profiles
│   ├── m6_fountain_encoder.py # FIXED: import paths, return type, codec param
│   ├── m7_multipass.py        # Unchanged (correct)
│   ├── m8_interleaver.py      # FIXED: accepts EncodedPacket directly, skips empty passes
│   ├── m9_metadata.py         # FIXED: crcmod at module level, hmac.compare_digest
│   ├── m10_serializer.py      # FIXED: add serialize_packet/deserialize_packet
│   ├── m11_transmitter.py     # FIXED: send_transfer() method, sleep-based rate control
│   └── pipeline.py            # Wires all sender modules
│
├── receiver/
│   ├── __init__.py
│   ├── m12_receiver.py        # FIXED: per-transfer buffers, correct max_packet_size
│   ├── m13_validator.py       # FIXED: all hard limits, timestamp replay, crcmod dep
│   ├── m14_auth_verifier.py   # Unchanged spec
│   ├── m15_pooler.py          # FIXED: stores EncodedPacket, readiness trigger, TTL
│   ├── m16_fountain_decoder.py# FIXED: unified pool decode, correct call signature
│   ├── m17_rs_decoder.py      # FIXED: real reedsolo decode
│   ├── m18_merkle_verifier.py # FIXED: real proof path traversal, uses models.py types
│   ├── m19_window_reassembler.py # FIXED: global chunk_id offset, state integration
│   ├── m20_file_reassembler.py   # FIXED: per-window padding, quarantine dir output
│   ├── m21_verifier.py        # FIXED: real Merkle root check, hmac.compare_digest
│   ├── m22_quarantine.py      # Unchanged spec
│   ├── m23_storage.py         # Unchanged spec
│   ├── m24_decompress.py      # NEW: decompress after file reassembly
│   └── pipeline.py
│
├── tests/
│   ├── __init__.py
│   ├── test_fountain.py       # Updated: chunk_ids checks, pass_id assignment
│   ├── test_chunker.py        # Updated: fix LossScenario field, classified key
│   ├── test_merkle.py
│   ├── test_rs.py
│   ├── test_compress.py       # NEW
│   ├── test_manifest.py
│   ├── test_validator.py
│   ├── test_pooler.py
│   ├── test_pipeline_e2e.py   # Updated: large file test (30MB+)
│   └── utils/
│       ├── __init__.py
│       └── loss_simulator.py  # FIXED: random.Random instances, burst stat bug
│
├── .devcontainer/
│   └── devcontainer.json
│
├── simulate_diode.py
├── requirements.txt           # Updated: add lz4, crcmod
├── setup.cfg
└── README.md
```

---

## UPDATED DEPENDENCIES

```
# requirements.txt

# Serialization
protobuf>=4.25.0

# Reed-Solomon (REAL implementation, not stub)
reedsolo>=1.7.0

# Cryptography
cryptography>=42.0.0

# BLAKE3
blake3>=0.4.0

# Numerics — CRITICAL for XOR performance
numpy>=1.26.0

# CRC32C — must be declared, not optional
crcmod>=1.7

# Compression — new
lz4>=4.3.2

# Testing
pytest>=8.0.0
pytest-cov>=4.0.0
```

---

## CRITICAL FIX 1 — EncodedPacket (fountain/interface.py)

This is the most impactful structural fix. Every other module depends on it.

```python
@dataclass
class EncodedPacket:
    """One fountain-encoded packet."""
    packet_id          : int        # unique within pass — for deduplication
    pass_id            : int        # which transmission pass (0, 1)
    seed               : int        # PRNG seed for this pass
    degree             : int        # number of source chunks XOR'd
    chunk_ids          : list[int]  # WHICH chunks were XOR'd — decoder reads directly
    data               : bytes      # XOR'd payload
    source_chunk_count : int        # K' = K + RS parity chunks
```

Why chunk_ids must be stored explicitly:
- Decoder must NOT re-derive chunk_ids by re-running PRNG
- Re-derivation requires both encoder and decoder to consume PRNG state
  in identical sequence — fragile, breaks silently if encoder logic changes
- Storing chunk_ids makes decoder completely independent of encoder internals
- Memory cost: ~degree * 4 bytes per packet, negligible vs payload

```python
@dataclass
class DecodeResult:
    """Result of fountain decode."""
    chunks          : list[bytes | None]  # None = not recovered
    success         : bool
    recovered_count : int
    missing_ids     : list[int]
    packets_used    : int
```

---

## CRITICAL FIX 2 — LT Encoder (fountain/lt_encoder.py)

Three specific fixes required:

### Fix A — Use numpy XOR (performance)
```python
import numpy as np

# BEFORE (slow — pure Python byte loop):
encoded_data = bytearray(chunk_size)
for idx in selected_indices:
    for j in range(chunk_size):
        encoded_data[j] ^= chunks[idx][j]

# AFTER (fast — numpy vectorized, ~100x faster):
encoded_data = np.zeros(chunk_size, dtype=np.uint8)
for idx in selected_indices:
    encoded_data ^= np.frombuffer(chunks[idx], dtype=np.uint8)
result_bytes = encoded_data.tobytes()
```

### Fix B — Use random.Random instance (correctness)
```python
# BEFORE (broken — global state):
random.seed(packet_seed)
degree = _robust_soliton_degree(K)
selected = random.sample(range(K), degree)

# AFTER (correct — instance state):
rng = random.Random(seed)   # created ONCE per encode() call
# then for each packet:
degree = _sample_degree_from_cdf(cdf, rng)      # uses rng instance
chunk_ids = sorted(rng.sample(range(K_prime), degree))  # uses rng instance
```

### Fix C — Store chunk_ids in EncodedPacket
```python
encoded_packets.append(EncodedPacket(
    packet_id          = packet_index,
    pass_id            = 0,           # caller sets actual pass_id
    seed               = seed,
    degree             = degree,
    chunk_ids          = chunk_ids,   # ← store directly
    data               = result_bytes,
    source_chunk_count = K_prime,
))
```

### Fix D — Correct Robust Soliton formula
```python
def _robust_soliton(K: int, c: float = 0.03, delta: float = 0.02) -> list[float]:
    """Standard Robust Soliton Distribution."""
    R = c * math.log(K / delta) * math.sqrt(K)
    pivot = max(1, int(math.floor(K / R)))

    # Ideal Soliton
    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))

    # Correction term tau
    tau = [0.0] * (K + 1)
    for d in range(1, pivot):
        tau[d] = R / (d * K)
    if pivot >= 1:
        tau[pivot] = (R * math.log(R / delta)) / K

    # Normalise
    mu_raw = [rho[d] + tau[d] for d in range(K + 1)]
    Z = sum(mu_raw[1:])
    return [0.0] + [mu_raw[d] / Z for d in range(1, K + 1)]
```

---

## CRITICAL FIX 3 — LT Decoder (fountain/lt_decoder.py)

Three specific fixes required:

### Fix A — Read chunk_ids directly from EncodedPacket
```python
# BEFORE (wrong — re-derives chunk selection):
def _build_graph(self, ...):
    random.seed(packet.seed)
    degree = _robust_soliton_degree(K)
    selected_indices = random.sample(range(K), degree)

# AFTER (correct — reads stored chunk_ids):
def _build_graph(self, ...):
    for pi, packet in enumerate(safe_packets):
        # chunk_ids already computed and stored by encoder
        valid_ids = [cid for cid in packet.chunk_ids if 0 <= cid < K_prime]
        if len(valid_ids) != packet.degree:
            continue  # malformed packet, skip
        packet_chunks[pi] = set(valid_ids)
        for cid in valid_ids:
            chunk_to_packets[cid].add(pi)
```

### Fix B — numpy XOR in peeling loop
```python
import numpy as np

# BEFORE (slow):
for j in range(chunk_size):
    residual[j] ^= known[j]

# AFTER (fast):
residual_arr = np.frombuffer(residual, dtype=np.uint8).copy()
known_arr    = np.frombuffer(known,    dtype=np.uint8)
residual_arr ^= known_arr
# write back as bytearray for continued mutation
packet_payload[other_pi] = bytearray(residual_arr.tobytes())
```

### Fix C — Use set for connected_chunks (O(1) removal)
```python
# BEFORE (O(n) removal):
check.connected_chunks.remove(chunk_id)

# AFTER (O(1) removal):
packet_chunks[other_pi].discard(chunk_id)   # already a set
```

### Fix D — Return graceful DecodeResult on empty pool
```python
# BEFORE (raises on empty):
if not pool:
    raise ValueError("packet pool cannot be empty")

# AFTER (graceful):
if not pool:
    return DecodeResult(
        chunks=[None] * K_prime,
        success=False,
        recovered_count=0,
        missing_ids=list(range(K_prime)),
        packets_used=0,
    )
```

---

## NEW MODULE — sender/m0_compress.py

**Role:** Compresses the input file before it enters the pipeline. This is the
single highest-impact performance improvement for large files. A 30MB text file
compresses to ~6MB with lz4, meaning 5x fewer chunks, 5x fewer packets, 5x
faster encoding and decoding.

**Why lz4 over zstd or gzip?**
- lz4 is optimized for speed, not maximum compression ratio
- Compress/decompress speed is ~500 MB/s vs ~50 MB/s for gzip
- For a data diode, transfer time dominates — fast compression wins
- zstd is an alternative for classified transfers where compression ratio
  matters more than speed

```python
import lz4.frame
import os

@dataclass
class CompressionResult:
    compressed_path  : str    # path to compressed temp file
    original_size    : int    # bytes before compression
    compressed_size  : int    # bytes after compression
    compression_ratio: float  # original / compressed
    algorithm        : str    # "lz4" or "none" (if already compressed)
    original_sha256  : str    # SHA-256 of ORIGINAL file (before compression)


def compress_file(input_path: str, output_path: str, algorithm: str = "lz4") -> CompressionResult:
    """
    Compress file for transfer.
    
    If file is already compressed (zip, gz, jpg, mp4, etc.) skip compression
    — these formats don't compress further and wasting CPU trying hurts speed.
    
    Parameters:
        input_path:  Path to original file
        output_path: Path to write compressed file
        algorithm:   "lz4" (fast) or "none" (skip compression)
    
    Returns:
        CompressionResult with sizes and ratio
    """
    ...

def should_compress(file_path: str) -> bool:
    """
    Decide whether compression will help based on file extension.
    
    Returns False for already-compressed formats:
    .jpg .jpeg .png .gif .mp4 .mkv .avi .zip .gz .bz2 .7z .rar .pdf
    
    Returns True for compressible formats:
    .txt .log .csv .json .xml .py .js .html .doc .xls
    """
    ...

SKIP_COMPRESSION_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff',
    '.mp4', '.mkv', '.avi', '.mov', '.wmv',
    '.zip', '.gz', '.bz2', '.7z', '.rar', '.lz4',
    '.mp3', '.aac', '.flac',
}
```

**Manifest impact:** Add these fields to `TransferManifest`:
```python
compression_algorithm : str    # "lz4" or "none"
compressed_size       : int    # bytes after compression (= file_size in manifest)
original_size         : int    # bytes before compression
original_sha256       : str    # SHA-256 of original (pre-compression) file
```

Receiver decompresses AFTER `m21_verifier` passes and BEFORE `m23_storage`
writes. The SHA-256 in the manifest verifies the **compressed** bytes in
transit. `original_sha256` verifies the decompressed result matches source.

---

## NEW MODULE — receiver/m24_decompress.py

**Role:** Decompresses the reconstructed file after all integrity checks pass.
Called by quarantine pipeline after m21 verification succeeds.

```python
def decompress_file(
    compressed_path : str,
    output_path     : str,
    algorithm       : str,    # from manifest.compression_algorithm
    expected_sha256 : str,    # manifest.original_sha256
) -> bool:
    """
    Decompress file and verify against original SHA-256.
    
    Returns True if decompression succeeds and hash matches.
    Returns False if decompression fails or hash mismatch.
    Never raises — all errors logged and returned as False.
    """
    ...
```

---

## UPDATED PROFILES (sender/m5_profile.py)

Caps passes at 2. Adjusts overhead for performance. Keeps full security.

```python
PROFILES = {
    # Small files (< 10 MB) — full checks, smaller windows
    ("small", "standard"):    Profile(
        passes=1, overhead_ratio=0.25, rs_config="RS(16,2)",
        interleave_depth=2, header_redundancy=3,
        window_size_bytes=16 * 1024 * 1024,   # 16 MB — small files fit in one window
    ),
    ("small", "critical"):    Profile(
        passes=2, overhead_ratio=0.25, rs_config="RS(16,4)",
        interleave_depth=3, header_redundancy=5,
        window_size_bytes=16 * 1024 * 1024,
    ),
    ("small", "classified"):  Profile(
        passes=2, overhead_ratio=0.30, rs_config="RS(32,8)",
        interleave_depth=4, header_redundancy=5,
        window_size_bytes=16 * 1024 * 1024,
    ),

    # Medium files (10 MB – 1 GB) — balanced
    ("medium", "standard"):   Profile(
        passes=1, overhead_ratio=0.20, rs_config="RS(32,4)",
        interleave_depth=3, header_redundancy=3,
        window_size_bytes=64 * 1024 * 1024,   # 64 MB windows
    ),
    ("medium", "critical"):   Profile(
        passes=2, overhead_ratio=0.20, rs_config="RS(32,6)",
        interleave_depth=4, header_redundancy=5,
        window_size_bytes=64 * 1024 * 1024,
    ),
    ("medium", "classified"): Profile(
        passes=2, overhead_ratio=0.25, rs_config="RS(32,8)",
        interleave_depth=5, header_redundancy=5,
        window_size_bytes=64 * 1024 * 1024,
    ),

    # Large files (> 1 GB) — performance priority, proportional windows
    ("large", "standard"):    Profile(
        passes=1, overhead_ratio=0.15, rs_config="RS(64,4)",
        interleave_depth=4, header_redundancy=3,
        window_size_bytes=128 * 1024 * 1024,  # 128 MB windows
    ),
    ("large", "critical"):    Profile(
        passes=2, overhead_ratio=0.15, rs_config="RS(64,6)",
        interleave_depth=6, header_redundancy=5,
        window_size_bytes=128 * 1024 * 1024,
    ),
    ("large", "classified"):  Profile(
        passes=2, overhead_ratio=0.20, rs_config="RS(64,8)",
        interleave_depth=8, header_redundancy=5,
        window_size_bytes=128 * 1024 * 1024,
    ),
}
```

**Profile validation: enforce MAX_PASSES = 2**
```python
@dataclass(frozen=True)
class Profile:
    passes: int
    ...
    def __post_init__(self):
        if not (1 <= self.passes <= 2):   # ← changed from 3 to 2
            raise ValueError(f"passes must be 1–2, got {self.passes}")
```

---

## UPDATED WINDOWING (sender/m1_windowing.py)

Window size is now proportional to file size, not fixed. Small files don't
need windowing at all — they fit in one window. Large files get larger windows
to reduce per-window overhead.

```python
def get_window_size_for_file(file_size_bytes: int, profile: Profile) -> int:
    """
    Compute window size proportional to file size.
    
    Rules:
    - File fits in one window → window_size = file_size (no windowing overhead)
    - Medium file → profile.window_size_bytes (64 MB default)
    - Large file  → profile.window_size_bytes (128 MB default)
    - Never exceed MAX_WINDOW_SIZE_BYTES
    - Never create a window with > MAX_CHUNKS_PER_WINDOW chunks
    
    Parameters:
        file_size_bytes: Original file size (AFTER compression)
        profile:         Transfer profile (has window_size_bytes)
    
    Returns:
        Window size in bytes to use for this transfer
    """
    # If file fits in one window, use file size directly
    # (avoids windowing overhead for small/medium files)
    if file_size_bytes <= profile.window_size_bytes:
        return file_size_bytes   # single window, no splitting needed

    # For large files, use profile window size
    return profile.window_size_bytes


def compute_windows(file_size_bytes: int, window_size_bytes: int) -> list[Window]:
    """Unchanged — still correct."""
    ...
```

**Do we still need windowing?**
Yes — but only for files that don't fit in one window. The updated logic above
means:
- 30MB file with 64MB profile window → 1 window (no windowing overhead at all)
- 500MB file with 64MB profile window → 8 windows
- 2GB file with 128MB profile window → 16 windows

This eliminates windowing overhead for the 30MB demo file entirely.

---

## FIXED RS ENCODER (sender/m4_rs_encoder.py)

Replace the fake duplication with real `reedsolo.RSCodec`:

```python
import reedsolo

def encode_with_rs(chunks: list[bytes], rs_config: RSConfig) -> list[bytes]:
    """
    Encode chunks with Reed-Solomon using reedsolo library.
    
    RSCodec(nsym) takes nsym = number of PARITY symbols (not total).
    rs_config.num_parity = rs_config.n - rs_config.k
    So: RSCodec(rs_config.num_parity)
    
    Note on reedsolo usage:
    - RSCodec works on byte strings
    - encode() returns data + parity as one bytestring
    - We split off the parity bytes and return them as separate parity chunks
    """
    if not chunks:
        raise ValueError("chunks list cannot be empty")
    
    chunk_size = len(chunks[0])
    num_parity_symbols = rs_config.num_parity  # = n - k
    
    # reedsolo operates on the entire chunk as a message
    # For chunk_size > 255 bytes we process in sub-blocks
    codec = reedsolo.RSCodec(num_parity_symbols)
    
    parity_chunks = []
    for chunk in chunks:
        encoded = codec.encode(chunk)
        # encoded = original_chunk_bytes + parity_bytes
        # parity_bytes length = num_parity_symbols
        parity_bytes = bytes(encoded[chunk_size:])
        # Pad parity_bytes to chunk_size so all chunks are equal length
        parity_chunk = parity_bytes.ljust(chunk_size, b'\x00')
        parity_chunks.append(parity_chunk)
    
    return list(chunks) + parity_chunks


def decode_with_rs(
    chunks_with_erasures: list[bytes | None],
    rs_config: RSConfig,
    chunk_size: int,
) -> list[bytes]:
    """
    Recover missing chunks using Reed-Solomon parity.
    
    Input: K data chunks + parity chunks, some may be None
    Output: K data chunks with gaps filled (parity stripped)
    """
    codec = reedsolo.RSCodec(rs_config.num_parity)
    K = len(chunks_with_erasures) - rs_config.num_parity
    
    # Find erasure positions
    erasures = [i for i, c in enumerate(chunks_with_erasures) if c is None]
    
    if len(erasures) > rs_config.num_parity:
        raise ValueError(
            f"Too many erasures ({len(erasures)}) for parity ({rs_config.num_parity})"
        )
    
    # Substitute zeros for None (reedsolo handles erasures by position)
    filled = [c if c is not None else bytes(chunk_size) for c in chunks_with_erasures]
    
    # Reconstruct using erasure positions
    message = b"".join(filled)
    try:
        decoded, _, _ = codec.decode(message, erase_pos=erasures)
        result_chunks = [
            decoded[i * chunk_size:(i + 1) * chunk_size]
            for i in range(K)
        ]
        return result_chunks
    except reedsolo.ReedSolomonError as e:
        raise ValueError(f"RS decode failed: {e}") from e
```

---

## FIXED MERKLE PROOF GENERATION (sender/m3_merkle.py)

Replace O(N) parent scan with O(1) reverse lookup:

```python
def build_merkle_tree(chunks: list[bytes]) -> dict:
    """Build tree — unchanged."""
    ...
    # After building, add reverse lookup
    child_to_parent: dict[str, str] = {}
    sibling_map: dict[str, str] = {}    # child_hash → sibling_hash
    is_left_child: dict[str, bool] = {} # child_hash → True if left child

    for node in tree.values():
        if node.left_child:
            child_to_parent[node.left_child]  = node.hash
            child_to_parent[node.right_child] = node.hash
            sibling_map[node.left_child]  = node.right_child
            sibling_map[node.right_child] = node.left_child
            is_left_child[node.left_child]  = True
            is_left_child[node.right_child] = False

    return tree, child_to_parent, sibling_map, is_left_child


def get_merkle_proof(tree_data: tuple, chunk_index: int, chunks: list[bytes]) -> list[MerkleProofStep]:
    """
    O(log N) proof generation using reverse lookup.
    
    Returns list of MerkleProofStep (sibling_hash + is_left flag).
    is_left=True means the sibling is to the LEFT of current node.
    """
    tree, child_to_parent, sibling_map, is_left_child = tree_data
    
    leaf_hash = _sha256_hash(chunks[chunk_index])
    current   = leaf_hash
    proof     = []
    
    while current in child_to_parent:
        sibling = sibling_map[current]
        proof.append(MerkleProofStep(
            sibling_hash = sibling,
            is_left      = is_left_child[current],  # True if WE are the right child (sibling is left)
        ))
        current = child_to_parent[current]
    
    return proof   # O(log N) steps, O(1) per step


def verify_merkle_proof(chunk_hash: str, proof: list[MerkleProofStep], expected_root: str) -> bool:
    """
    Verify proof with correct left/right ordering.
    """
    current = chunk_hash
    for step in proof:
        if step.is_left:
            # Sibling is left, current is right
            combined = bytes.fromhex(step.sibling_hash) + bytes.fromhex(current)
        else:
            # Current is left, sibling is right
            combined = bytes.fromhex(current) + bytes.fromhex(step.sibling_hash)
        current = hashlib.sha256(combined).hexdigest()
    return hmac.compare_digest(current, expected_root)
```

---

## FIXED MULTI-PASS DECODE (receiver/m16_fountain_decoder.py)

```python
def decode_window(
    self,
    pooled_packets : list[EncodedPacket],   # ALL passes, unified pool
    K_prime        : int,
    chunk_size     : int,
) -> DecodeResult:
    """
    Decode unified pool (all passes combined) in ONE decode call.
    
    CRITICAL: Do NOT decode passes separately and merge results.
    All packets from all passes feed into ONE Tanner graph.
    Cross-pass recovery only works when packets are in the same graph.
    """
    if not pooled_packets:
        return DecodeResult(
            chunks=[None] * K_prime,
            success=False,
            recovered_count=0,
            missing_ids=list(range(K_prime)),
            packets_used=0,
        )
    
    # Unified decode — decoder handles multi-pass packets transparently
    # because each packet carries its own chunk_ids regardless of pass
    decoder = get_decoder(self.codec)
    return decoder.decode(pooled_packets, K_prime=K_prime)
```

---

## FIXED POOLER (receiver/m15_pooler.py)

```python
@dataclass
class WindowPool:
    """Packet pool for one window."""
    transfer_id  : str
    window_id    : int
    packets      : dict[tuple[int,int,int], EncodedPacket]  # (window,pass,packet) → EncodedPacket
    created_at   : float
    last_packet_at: float    # TTL based on LAST activity, not oldest packet
    status       : str       # "collecting" | "ready" | "decoding" | "done" | "failed"

def add_packet(self, transfer_id, window_id, packet: EncodedPacket) -> bool:
    """Store EncodedPacket directly — not PooledPacket conversion."""
    dedup_key = (window_id, packet.pass_id, packet.packet_id)
    if dedup_key in self.dedup_sets[transfer_id]:
        return False   # duplicate
    
    # Pool size cap — prevent memory exhaustion
    current_count = self.get_packet_count(transfer_id, window_id)
    if current_count >= self._max_pool_size(K_prime, num_passes):
        return False   # pool saturated, no benefit adding more
    
    self.pools[transfer_id][window_id][dedup_key] = packet
    self.dedup_sets[transfer_id].add(dedup_key)
    self.last_activity[transfer_id] = time.time()  # TTL on last activity
    return True

def is_ready_to_decode(self, transfer_id, window_id, K_prime) -> bool:
    """Pool ready when packet count >= K_prime * 1.05 OR idle timeout."""
    count = self.get_packet_count(transfer_id, window_id)
    if count >= K_prime * 1.05:
        return True
    idle_seconds = time.time() - self.last_activity.get(transfer_id, 0)
    if idle_seconds > WINDOW_TIMEOUT:
        return True   # decode with whatever we have
    return False

def get_unified_pool(self, transfer_id, window_id) -> list[EncodedPacket]:
    """Return all packets as flat list — ready for fountain decoder."""
    return list(self.pools[transfer_id][window_id].values())
```

---

## FIXED TRANSMITTER (sender/m11_transmitter.py)

```python
def send_transfer(
    self,
    remote_addr     : tuple[str, int],
    manifest_bytes  : bytes,
    header_redundancy: int,
    windows_packets : list[list[EncodedPacket]],  # [window_id][packet_index]
    serializer,      # m10_serializer instance
) -> dict:
    """
    Transmit a complete transfer in correct sequence:
    1. Manifest × header_redundancy
    2. Per-window packets in interleaved order
    3. Footer marker × 3
    
    Rate control: sleep-based, configurable pps.
    Returns stats dict with packet counts.
    """
    stats = {"manifest_sent": 0, "data_sent": 0, "bytes_sent": 0}
    gap = 1.0 / self.config.packets_per_second if self.config.packets_per_second > 0 else 0

    # Phase 0: manifest
    for _ in range(header_redundancy):
        self._send_raw(remote_addr, manifest_bytes)
        stats["manifest_sent"] += 1
        if gap: time.sleep(gap)

    # Phase 1..N: window data
    for window_packets in windows_packets:
        for packet in window_packets:
            packet_bytes = serializer.serialize_packet(packet)
            self._send_raw(remote_addr, packet_bytes)
            stats["data_sent"] += 1
            stats["bytes_sent"] += len(packet_bytes)
            if gap: time.sleep(gap)

    # Footer
    footer = f"TRANSFER_END:{transfer_id}".encode()
    for _ in range(3):
        self._send_raw(remote_addr, footer)
        if gap: time.sleep(gap)

    return stats

def _send_raw(self, addr: tuple, data: bytes) -> None:
    """Send bytes, create socket if needed. sleep-based rate control handled by caller."""
    if self.socket is None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
    self.socket.sendto(data, addr)
```

---

## FIXES FOR TEST FILES

### tests/test_chunker.py

```python
# Fix 1 — LossScenario test: import from loss_simulator, not models
from tests.utils.loss_simulator import LossScenario as SimLossScenario

def test_loss_scenario_creation(self):
    scenario = SimLossScenario(random_loss_rate=0.10)
    assert scenario.random_loss_rate == 0.10

# Fix 2 — Classified profile test: check get_profile(), not direct key lookup
def test_get_profile_classified_any_size(self):
    """Classified profile applies regardless of file size."""
    for size in [100_000, 100_000_000, 10_000_000_000]:
        profile = get_profile(size, "classified")
        assert profile.passes >= 1
        assert profile.rs_k >= 8
```

### tests/test_fountain.py

```python
# Fix 1 — Add chunk_ids to reproducibility test
def test_encode_reproducibility(self):
    packets1 = encoder.encode(chunks, seed=123, overhead_ratio=0.5)
    packets2 = encoder.encode(chunks, seed=123, overhead_ratio=0.5)
    for p1, p2 in zip(packets1, packets2):
        assert p1.degree    == p2.degree
        assert p1.seed      == p2.seed
        assert p1.data      == p2.data
        assert p1.chunk_ids == p2.chunk_ids   # ← add this

# Fix 2 — Empty pool returns graceful result, not ValueError
def test_decode_empty_pool_returns_all_missing(self):
    decoder = LTDecoder()
    result  = decoder.decode([], K_prime=50)
    assert not result.success
    assert result.recovered_count == 0
    assert all(c is None for c in result.chunks)

# Fix 3 — Multi-pass roundtrip sets pass_id correctly
def test_roundtrip_many_passes(self):
    all_encoded = []
    for pass_id in range(2):   # ← changed from 3 to 2
        encoded = encoder.encode(chunks, seed=pass_id * 1000, overhead_ratio=0.5)
        for p in encoded:
            p.pass_id = pass_id   # ← set pass_id
        all_encoded.extend(encoded)
    result = decoder.decode(all_encoded, K_prime=K)
    assert result.success
```

---

## IMPLEMENTATION ORDER FOR REMAINING WORK

Fix in this exact sequence — each fix unblocks the next:

```
IMMEDIATE FIXES (unblock correctness)
──────────────────────────────────────
 Fix 1   fountain/interface.py        Expand EncodedPacket with chunk_ids, packet_id, pass_id
 Fix 2   fountain/lt_encoder.py       numpy XOR + random.Random + correct RS + store chunk_ids
 Fix 3   fountain/lt_decoder.py       Read chunk_ids directly + numpy XOR + set for chunks
         → RUN: pytest tests/test_fountain.py — all tests must pass
 Fix 4   sender/m3_merkle.py          O(1) proof generation + correct left/right ordering
         → RUN: pytest tests/test_merkle.py
 Fix 5   sender/m4_rs_encoder.py      Real reedsolo encoding (not fake duplication)
         → RUN: pytest tests/test_rs.py
 Fix 6   sender/m10_serializer.py     Add serialize_packet / deserialize_packet
         → RUN: pytest tests/test_manifest.py

PERFORMANCE ADDITIONS
──────────────────────────────────────
 Add 7   sender/m0_compress.py        NEW: lz4 compression
         receiver/m24_decompress.py   NEW: lz4 decompression + verify original_sha256
         → RUN: pytest tests/test_compress.py
 Fix 8   sender/m11_transmitter.py    Add send_transfer() + sleep-based rate control
 Fix 9   receiver/m12_receiver.py     Per-transfer buffers + correct max_packet_size
 Fix 10  receiver/m15_pooler.py       Store EncodedPacket + readiness trigger + activity TTL
 Fix 11  receiver/m16_fountain_decoder Unified pool decode (NOT per-pass merge)
 Fix 12  receiver/m13_validator.py    All hard limits + timestamp replay + crcmod in requirements
         → RUN: pytest tests/test_validator.py + tests/test_pooler.py

INTEGRATION
──────────────────────────────────────
 Fix 13  sender/pipeline.py           Wire: compress → manifest → window → chunk → RS → fountain
                                             → interleave → transmit
         receiver/pipeline.py         Wire: receive → validate → pool → decode → RS → merkle
                                             → reassemble → verify → decompress → quarantine → store
 Fix 14  simulate_diode.py            Two-process test with 30MB file, measure time
         → RUN: pytest tests/test_pipeline_e2e.py
         → TARGET: 30MB file completes in under 60 seconds
```

---

## PERFORMANCE TARGETS

After all fixes, these should be achievable on Codespaces (2 CPU, 8GB RAM):

```
File Size     Criticality    Target Time    Notes
──────────────────────────────────────────────────────────
1 MB          standard       < 5 seconds    1 pass, 1 window, compressed
10 MB         standard       < 15 seconds   1 pass, 1 window, compressed
30 MB         standard       < 45 seconds   1 pass, 1 window, compressed
30 MB         critical       < 90 seconds   2 passes, compressed
100 MB        standard       < 3 minutes    1 pass, 2 windows, compressed
```

If 30MB still exceeds 60 seconds after all fixes, profile with:
```bash
python -m cProfile -o profile.out simulate_diode.py --file test_30mb.txt
python -m pstats profile.out
# Sort by cumulative time, look at top 20 functions
```

---

## KEY INVARIANTS — UNCHANGED FROM ORIGINAL

```
1. Receiver never sends. No outbound socket. No exceptions.
2. IFountainEncoder/IFountainDecoder are the only way pipeline accesses codecs.
3. Manifest always transmitted before data packets.
4. Decoder hard limits checked BEFORE any graph memory allocated.
5. No file reaches secure storage without passing all 8 verification gates.
6. All chunks equal size. Last chunk zero-padded. Receiver strips padding.
7. Different passes use different seeds derived from hash(transfer_id:window_id:pass_id).
8. MAX_PASSES = 2 (performance constraint, replaces previous MAX_PASSES = 3).
9. Compression applied before chunking, decompression after final verification.
10. Window size proportional to file size — single window for files < window_size_bytes.
```