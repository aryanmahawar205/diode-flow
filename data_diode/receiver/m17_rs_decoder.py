"""
receiver/m17_rs_decoder.py — Reed-Solomon decoder wrapper.

Role:
Decode chunk erasures using the sender's RS configuration.

Design:
- Wrap sender.m4_rs_encoder decode logic so receiver uses the same simplified
  RS placeholder layer until Phase 3 proper RS is available.
- Maintain clear separation between receiver and sender by importing only the
  RSConfig and decode API.
"""

from __future__ import annotations

import logging
from typing import List

from data_diode.sender.m4_rs_encoder import RSConfig, decode_with_rs

logger = logging.getLogger(__name__)


class ReedSolomonDecoder:
    """
    Simplified RS decoder for Phase 2.
    """

    def __init__(self, rs_config: RSConfig):
        if not isinstance(rs_config, RSConfig):
            raise ValueError("rs_config must be an RSConfig instance")

        self.rs_config = rs_config

    def decode(self, chunks_with_erasures: List[bytes | None]) -> List[bytes]:
        """
        Attempt to recover original data chunks using RS parity.

        Parameters:
            chunks_with_erasures: List of bytes or None for each chunk slot.

        Returns:
            Recovered original data chunks.

        Raises:
            ValueError: if decode cannot recover the original data.
        """
        logger.debug(
            "Decoding %d erasure slots with RS(%d, %d)",
            len(chunks_with_erasures),
            self.rs_config.n,
            self.rs_config.k,
        )

        recovered = decode_with_rs(chunks_with_erasures, self.rs_config)
        logger.debug("RS decode recovered %d chunks", len(recovered))
        return recovered

    def is_recoverable(self, erasure_count: int) -> bool:
        """
        Check if the number of missing chunks is recoverable.
        """
        return erasure_count <= self.rs_config.num_parity
