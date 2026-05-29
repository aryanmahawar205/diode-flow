"""
Reed-Solomon encoding using reedsolo library.
Adds parity chunks to each window's chunk list.
Proper chunk-level erasure coding: treats each byte position across chunks as a codeword.
"""
from __future__ import annotations
import logging
import reedsolo
import numpy as np
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class RSConfig:
    n: int   # total symbols (data + parity) per block
    k: int   # parity count per block

    @property
    def data_per_block(self) -> int:
        return self.n - self.k


def encode_rs(chunks: list[bytes], config: RSConfig) -> list[bytes]:
    """
    Add Reed-Solomon parity chunks.
    Treats each byte position across chunks as an RS codeword.
    """
    if not chunks:
        return []

    chunk_size   = len(chunks[0])
    parity_count = config.k
    block_size   = config.data_per_block
    codec        = reedsolo.RSCodec(parity_count)

    all_parity_chunks = []

    # Process in blocks
    for block_start in range(0, len(chunks), block_size):
        block = chunks[block_start : block_start + block_size]
        actual_block_size = len(block)
        
        # Prepare data array for this block
        data_arr = np.frombuffer(b"".join(block), dtype=np.uint8).reshape(actual_block_size, chunk_size)
        
        # Generate parity
        # We need parity_count parity chunks for this block
        parity_arr = np.zeros((parity_count, chunk_size), dtype=np.uint8)
        
        # This loop is the bottleneck in pure Python
        for j in range(chunk_size):
            # Take a vertical slice (one byte from every chunk in the block)
            codeword = data_arr[:, j].tobytes()

            # Encode that byte-slice to get its ecc bytes
            ecc_bytes = codec.encode(codeword)[actual_block_size:]

            # Store the resulting ecc bytes vertically in the parity array
            parity_arr[:, j] = np.frombuffer(ecc_bytes, dtype=np.uint8)
        
        if block_start % (block_size * 10) == 0:
            logger.debug(f"RS encoded {block_start} chunks...")

        for p in range(parity_count):
            all_parity_chunks.append(parity_arr[p].tobytes())

    result = list(chunks) + all_parity_chunks
    logger.debug(f"RS encode: {len(chunks)} data → {len(result)} total chunks")
    return result


def decode_rs(chunks_with_gaps: list[bytes | None], config: RSConfig,
              chunk_size: int) -> list[bytes | None]:
    """
    Recover missing chunks using RS parity.
    """
    if not chunks_with_gaps:
        return []

    if config.k <= 0:
        return list(chunks_with_gaps)

    parity_count = config.k
    block_size   = config.data_per_block
    
    # Calculate how many blocks we have
    # Total chunks = D + n_blocks * P
    # n_blocks = ceil(D / block_size)
    # This is tricky because we don't know D directly.
    # But we know that for each block of up to block_size chunks, we added parity_count chunks.
    # So total_chunks = sum over blocks (len(block) + parity_count)
    
    # Let's find n_blocks
    # K_prime = total_chunks
    total_chunks = len(chunks_with_gaps)
    # Each block contributes (actual_block_size + parity_count) chunks.
    # Except the last block which might have fewer than block_size data chunks.
    
    # Since all parity chunks are at the end, we can separate them if we know how many there are.
    # The number of blocks is ceil(D / block_size).
    # Let D be total data chunks. D = total_chunks - n_blocks * parity_count.
    # n_blocks = (D + block_size - 1) // block_size
    
    # We can iterate to find D:
    D = 0
    for n_b in range(1, total_chunks // parity_count + 1):
        temp_D = total_chunks - n_b * parity_count
        if temp_D > 0 and (temp_D + block_size - 1) // block_size == n_b:
            D = temp_D
            n_blocks = n_b
            break
    else:
        # Fallback for 1 block or if logic above fails
        n_blocks = 1
        D = total_chunks - parity_count

    data_chunks   = chunks_with_gaps[:D]
    parity_chunks = chunks_with_gaps[D:]
    
    codec     = reedsolo.RSCodec(parity_count)
    recovered = list(data_chunks)
    
    spam_count = 0
    for b in range(n_blocks):
        d_start = b * block_size
        d_end   = min((b + 1) * block_size, D)
        p_start = b * parity_count
        p_end   = (b + 1) * parity_count
        
        block_data   = data_chunks[d_start:d_end]
        block_parity = parity_chunks[p_start:p_end]
        
        erasures = [i for i, c in enumerate(block_data) if c is None]
        p_erasures = [i + len(block_data) for i, c in enumerate(block_parity) if c is None]
        all_erasures = erasures + p_erasures
        
        if not erasures:
            continue
            
        if len(all_erasures) > parity_count:
            spam_count += 1
            if spam_count <= 5:
                logger.debug(f"Too many erasures in block {b}: {len(all_erasures)} > {parity_count}")
            elif spam_count == 6:
                logger.debug("RS: Further warnings suppressed for this window...")
            continue
            
        # Try to recover
        try:
            # Fill Nones with zeros
            filled_data = [c if c is not None else bytes(chunk_size) for c in block_data]
            filled_parity = [c if c is not None else bytes(chunk_size) for c in block_parity]
            
            data_arr = np.frombuffer(b"".join(filled_data), dtype=np.uint8).reshape(len(block_data), chunk_size)
            parity_arr = np.frombuffer(b"".join(filled_parity), dtype=np.uint8).reshape(len(block_parity), chunk_size)
            
            # Optimized recovery: only one loop over chunk_size
            new_data_arr = np.zeros((len(block_data), chunk_size), dtype=np.uint8)
            for j in range(chunk_size):
                codeword = np.concatenate([data_arr[:, j], parity_arr[:, j]]).tobytes()
                # reedsolo.decode returns (decoded_msg, decoded_msgecc, erasures_count)
                decoded_msg_tuple = codec.decode(codeword, erase_pos=all_erasures)
                decoded_data = decoded_msg_tuple[0]
                new_data_arr[:, j] = np.frombuffer(decoded_data, dtype=np.uint8)
            
            for idx in erasures:
                recovered[d_start + idx] = new_data_arr[idx].tobytes()
                
            logger.debug(f"RS recovered {len(erasures)} chunks in block {b}")
            
        except Exception as e:
            logger.warning(f"RS block {b} recovery failed: {e}")

    return recovered
