"""
receiver/m17_rs_decoder.py — Reed-Solomon decoder wrapper.
"""

from __future__ import annotations

import logging
from typing import List
from sender.m4_rs_encoder import RSConfig, decode_with_rs

logger = logging.getLogger(__name__)


class ReedSolomonDecoder:
    """
    Reed-Solomon decoder for receiver pipeline.
    """

    def __init__(self, rs_config: RSConfig = None):
        self.rs_config = rs_config

    def decode(self, chunks_with_erasures: List[bytes | None]) -> List[bytes]:
        """
        Attempt to recover original data chunks using RS parity.
        Uses the internal rs_config.
        """
        if not self.rs_config:
            raise ValueError("ReedSolomonDecoder initialized without RSConfig")
        return decode_with_rs(chunks_with_erasures, self.rs_config)

    def recover(self, chunks_with_erasures: List[bytes | None], rs_n: int, rs_k: int, chunk_size: int) -> List[bytes]:
        """
        Attempt to recover original data chunks using RS parity.
        """
        config = RSConfig(n=rs_n, k=rs_k)
        return decode_with_rs(chunks_with_erasures, config)

    def is_recoverable(self, erasure_count: int) -> bool:
        """
        Check if the number of missing chunks is recoverable.
        """
        if self.rs_config:
            return erasure_count <= self.rs_config.num_parity
        return False
