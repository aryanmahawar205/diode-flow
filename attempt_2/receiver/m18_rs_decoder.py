"""
Reed-Solomon recovery for chunks still missing after fountain decode.
Uses same reedsolo library and config as sender.
"""
from __future__ import annotations
import logging
from common.models import TransferManifest
from sender.m5_rs_encoder import decode_rs, RSConfig

logger = logging.getLogger(__name__)


def recover(chunks: list[bytes | None], manifest: TransferManifest,
            chunk_size: int) -> list[bytes | None]:
    """
    Attempt RS recovery on chunks that fountain decode missed.
    Returns list with gaps filled where RS parity allows.
    """
    missing = sum(1 for c in chunks if c is None)
    if missing == 0:
        return chunks

    config = RSConfig(n=manifest.rs_n, k=manifest.rs_k)
    logger.info(f"RS recovery: {missing} missing chunks, "
                f"parity={config.k}")

    try:
        return decode_rs(chunks, config, chunk_size)
    except Exception as e:
        logger.warning(f"RS recovery failed: {e}")
        return chunks
