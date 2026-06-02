"""Packet loss injection for testing. Uses random.Random instances — never global state."""
from __future__ import annotations
import random
from dataclasses import dataclass


@dataclass
class LossScenario:
    random_loss_rate  : float = 0.0
    burst_loss_rate   : float = 0.0
    burst_length      : int   = 100
    corruption_rate   : float = 0.0


def apply_random_loss(packets: list, rate: float, seed: int = 0) -> list:
    rng = random.Random(seed)
    return [None if rng.random() < rate else p for p in packets]


def apply_burst_loss(packets: list, burst_rate: float,
                     burst_length: int, seed: int = 0) -> list:
    rng    = random.Random(seed)
    result = list(packets)
    i      = 0
    while i < len(result):
        if rng.random() < burst_rate:
            for j in range(i, min(i + burst_length, len(result))):
                result[j] = None
            i += burst_length
        else:
            i += 1
    return result


def apply_scenario(packets: list, scenario: LossScenario, seed: int = 0) -> tuple:
    result = list(packets)
    if scenario.random_loss_rate > 0:
        result = apply_random_loss(result, scenario.random_loss_rate, seed)
    if scenario.burst_loss_rate > 0:
        result = apply_burst_loss(result, scenario.burst_loss_rate,
                                  scenario.burst_length, seed + 1)
    lost = sum(1 for p in result if p is None)
    return result, {"total_loss": lost, "loss_rate": lost / max(len(result), 1)}


SCENARIO_NONE      = LossScenario()
SCENARIO_5PCT      = LossScenario(random_loss_rate=0.05)
SCENARIO_10PCT     = LossScenario(random_loss_rate=0.10)
SCENARIO_BURST     = LossScenario(burst_loss_rate=0.005, burst_length=200)
SCENARIO_COMBINED  = LossScenario(random_loss_rate=0.05, burst_loss_rate=0.005,
                                   burst_length=100)
