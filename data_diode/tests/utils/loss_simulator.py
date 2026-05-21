"""
tests/utils/loss_simulator.py — Packet Loss and Corruption Simulator

Role:
Simulate various failure scenarios for testing receiver robustness:
- Random packet loss (uniform random, tunable percentage)
- Burst loss (consecutive packet loss, simulates network hiccup)
- Bit corruption (random bits flipped, simulates data corruption)

Design:
- Input: list of packets
- Output: same list with some packets dropped or corrupted
- Parameters: loss_rate (0-1), burst_size (0-inf), corruption_rate (0-1)
"""

import random
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class LossScenario:
    """Parameters for a loss scenario."""
    random_loss_rate: float = 0.0       # Probability each packet is lost (0-1)
    burst_loss_rate: float = 0.0        # Probability burst loss starts (0-1)
    burst_length: int = 500             # Packets per burst
    bit_corruption_rate: float = 0.0    # Probability a bit is flipped (0-1e-6)


class LossSimulator:
    """Simulates packet loss and corruption."""
    
    @staticmethod
    def apply_random_loss(packets: List[bytes], loss_rate: float, seed: Optional[int] = None) -> Tuple[List[Optional[bytes]], List[int]]:
        """
        Apply uniform random packet loss.
        
        Args:
            packets: List of packet bytes
            loss_rate: Probability each packet is lost (0-1)
            seed: Random seed (for reproducibility)
        
        Returns:
            (packets_with_loss, lost_indices) where lost packets are None
        """
        if not (0 <= loss_rate <= 1):
            raise ValueError(f"loss_rate must be 0-1, got {loss_rate}")
        
        if seed is not None:
            random.seed(seed)
        
        result = []
        lost_indices = []
        
        for i, packet in enumerate(packets):
            if random.random() < loss_rate:
                result.append(None)
                lost_indices.append(i)
            else:
                result.append(packet)
        
        return result, lost_indices
    
    @staticmethod
    def apply_burst_loss(packets: List[bytes], burst_rate: float, burst_length: int, seed: Optional[int] = None) -> Tuple[List[Optional[bytes]], List[int]]:
        """
        Apply burst loss (consecutive packets lost at random intervals).
        
        Args:
            packets: List of packet bytes
            burst_rate: Probability a burst starts at each packet (0-1)
            burst_length: Number of packets per burst
            seed: Random seed
        
        Returns:
            (packets_with_loss, lost_indices)
        """
        if not (0 <= burst_rate <= 1):
            raise ValueError(f"burst_rate must be 0-1, got {burst_rate}")
        
        if burst_length < 1:
            raise ValueError(f"burst_length must be >= 1, got {burst_length}")
        
        if seed is not None:
            random.seed(seed)
        
        result = list(packets)
        lost_indices = []
        in_burst = False
        burst_counter = 0
        
        for i in range(len(result)):
            # Decide if burst starts
            if not in_burst and random.random() < burst_rate:
                in_burst = True
                burst_counter = 0
            
            # If in burst, drop packet
            if in_burst:
                result[i] = None
                lost_indices.append(i)
                burst_counter += 1
                if burst_counter >= burst_length:
                    in_burst = False
        
        return result, lost_indices
    
    @staticmethod
    def apply_bit_corruption(packet: bytes, corruption_rate: float, seed: Optional[int] = None) -> bytes:
        """
        Flip random bits in a packet.
        
        Args:
            packet: Packet bytes
            corruption_rate: Probability each bit is flipped (0-1e-6, very small)
            seed: Random seed
        
        Returns:
            Corrupted packet bytes
        """
        if corruption_rate < 0 or corruption_rate > 1e-4:
            raise ValueError(f"corruption_rate should be << 1, got {corruption_rate}")
        
        if seed is not None:
            random.seed(seed)
        
        if corruption_rate == 0:
            return packet
        
        # Convert to bytearray for modification
        corrupted = bytearray(packet)
        num_bits = len(corrupted) * 8
        num_flips = int(num_bits * corruption_rate)
        
        # Randomly select bit positions to flip
        for _ in range(num_flips):
            byte_idx = random.randint(0, len(corrupted) - 1)
            bit_idx = random.randint(0, 7)
            corrupted[byte_idx] ^= (1 << bit_idx)
        
        return bytes(corrupted)
    
    @staticmethod
    def apply_corruption_to_packets(packets: List[Optional[bytes]], corruption_rate: float, seed: Optional[int] = None) -> List[Optional[bytes]]:
        """
        Apply bit corruption to all present packets.
        
        Args:
            packets: List of packet bytes (None entries skipped)
            corruption_rate: Bit flip probability
            seed: Random seed
        
        Returns:
            Packets with bit corruption applied
        """
        if seed is not None:
            random.seed(seed)
        
        result = []
        for packet in packets:
            if packet is None:
                result.append(None)
            else:
                result.append(LossSimulator.apply_bit_corruption(packet, corruption_rate))
        
        return result
    
    @staticmethod
    def apply_scenario(packets: List[bytes], scenario: LossScenario, seed: Optional[int] = None) -> Tuple[List[Optional[bytes]], dict]:
        """
        Apply complete loss scenario.
        
        Args:
            packets: List of packet bytes
            scenario: LossScenario with parameters
            seed: Random seed
        
        Returns:
            (packets_with_loss, stats)
        """
        if seed is not None:
            random.seed(seed)
        
        stats = {
            "original_count": len(packets),
            "random_loss_count": 0,
            "burst_loss_count": 0,
            "corruption_count": 0,
        }
        
        result = list(packets)
        lost_to_drop = set()
        
        # Apply random loss
        if scenario.random_loss_rate > 0:
            result_with_random, random_lost = LossSimulator.apply_random_loss(result, scenario.random_loss_rate)
            result = result_with_random
            lost_to_drop.update(random_lost)
            stats["random_loss_count"] = len(random_lost)
        
        # Apply burst loss
        if scenario.burst_loss_rate > 0:
            result_with_burst, burst_lost = LossSimulator.apply_burst_loss(result, scenario.burst_loss_rate, scenario.burst_length)
            result = result_with_burst
            for idx in burst_lost:
                if result[idx] is None:
                    lost_to_drop.add(idx)
            stats["burst_loss_count"] = len([i for i in burst_lost if i not in lost_to_drop])
        
        # Apply bit corruption
        if scenario.bit_corruption_rate > 0:
            result = LossSimulator.apply_corruption_to_packets(result, scenario.bit_corruption_rate)
            stats["corruption_count"] = sum(1 for p in result if p is not None)
        
        stats["total_loss_count"] = len([p for p in result if p is None])
        stats["loss_rate"] = stats["total_loss_count"] / len(result) if result else 0
        
        return result, stats


# Common scenarios for testing
SCENARIO_NO_LOSS = LossScenario()
SCENARIO_10_PERCENT_LOSS = LossScenario(random_loss_rate=0.10)
SCENARIO_20_PERCENT_LOSS = LossScenario(random_loss_rate=0.20)
SCENARIO_BURST_5SEC = LossScenario(burst_loss_rate=0.01, burst_length=500)
SCENARIO_COMBINED = LossScenario(random_loss_rate=0.05, burst_loss_rate=0.01, burst_length=200)
