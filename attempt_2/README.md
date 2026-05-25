# Software Data Diode

A strictly one-way file transfer system using UDP loopback.

## Features
- **Strictly One-Way:** Receiver never sends data back.
- **Resilient:** Uses LT Fountain codes and Reed-Solomon erasure coding.
- **Large File Support:** Sliding window processing handles up to 10GB files with low RAM usage.
- **Secure:** CRC32C, BLAKE3-MAC, and Merkle tree verification.
- **Streaming:** End-to-end streaming compression and decompression.

## Installation
```bash
pip install -r requirements.txt
```

## Running the Demo
```bash
python run_demo.py --file your_file.txt
```

## Testing
```bash
pytest tests/ -v
```
