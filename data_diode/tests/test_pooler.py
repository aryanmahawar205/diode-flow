"""
tests/test_pooler.py — Tests for packet pooling and deduplication.
"""

import pytest
import time
from data_diode.receiver.m15_pooler import PacketPool
from data_diode.fountain.interface import EncodedPacket

def test_pool_add_packet():
    pool = PacketPool()
    packet = EncodedPacket(
        packet_id=1, pass_id=0, seed=123, degree=1, chunk_ids=[0],
        data=b"data", source_chunk_count=10
    )
    
    assert pool.add_packet("transfer-1", 0, packet) is True
    assert pool.get_packet_count("transfer-1", 0) == 1
    
    # Duplicate
    assert pool.add_packet("transfer-1", 0, packet) is False
    assert pool.get_packet_count("transfer-1", 0) == 1

def test_pool_readiness():
    pool = PacketPool()
    # K_prime = 100, ready at 1.05 * 100 = 105 packets
    K_prime = 100
    
    for i in range(100):
        packet = EncodedPacket(
            packet_id=i, pass_id=0, seed=123, degree=1, chunk_ids=[0],
            data=b"data", source_chunk_count=K_prime
        )
        pool.add_packet("t1", 0, packet)
        
    assert pool.is_ready_to_decode("t1", 0, K_prime) is False
    
    # 5 more packets to reach 105
    for i in range(100, 105):
        packet = EncodedPacket(
            packet_id=i, pass_id=0, seed=123, degree=1, chunk_ids=[0],
            data=b"data", source_chunk_count=K_prime
        )
        pool.add_packet("t1", 0, packet)

    assert pool.is_ready_to_decode("t1", 0, K_prime) is True

def test_pool_clear_window():
    pool = PacketPool()
    packet = EncodedPacket(
        packet_id=1, pass_id=0, seed=123, degree=1, chunk_ids=[0],
        data=b"data", source_chunk_count=10
    )
    pool.add_packet("t1", 0, packet)
    assert pool.total_packets == 1
    
    pool.clear_window("t1", 0)
    assert pool.get_packet_count("t1", 0) == 0
    assert pool.total_packets == 0

def test_pool_cleanup_ttl():
    pool = PacketPool(ttl_seconds=1)
    packet = EncodedPacket(
        packet_id=1, pass_id=0, seed=123, degree=1, chunk_ids=[0],
        data=b"data", source_chunk_count=10
    )
    pool.add_packet("t1", 0, packet)
    
    time.sleep(1.1)
    removed = pool.cleanup_old_transfers()
    assert removed == 1
    assert pool.get_packet_count("t1", 0) == 0
