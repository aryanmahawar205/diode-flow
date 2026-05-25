"""
Tests for receiver Reed-Solomon decoder wrapper.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from receiver.m17_rs_decoder import ReedSolomonDecoder
from sender.m4_rs_encoder import RSConfig


def test_rs_decoder_recoverable():
    """RS decoder should recover when erasures are within parity limit."""
    rs_config = RSConfig(n=8, k=6)
    decoder = ReedSolomonDecoder(rs_config=rs_config)

    chunks = [b"chunk0", b"chunk1", None, b"chunk3", None, b"chunk5", b"chunk6", b"chunk7"]
    recovered = decoder.decode(chunks)

    assert len(recovered) == 6
    assert all(isinstance(chunk, bytes) for chunk in recovered)


def test_rs_decoder_too_many_erasures():
    """RS decoder should fail if missing chunks exceed parity count."""
    rs_config = RSConfig(n=8, k=6)
    decoder = ReedSolomonDecoder(rs_config=rs_config)

    chunks = [None, None, None, b"chunk3", None, b"chunk5", b"chunk6", b"chunk7"]

    try:
        decoder.decode(chunks)
        assert False, "decode should raise ValueError for too many erasures"
    except ValueError as exc:
        assert "Too many erasures" in str(exc)
