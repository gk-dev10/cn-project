"""Packet-loss simulation for Module 22."""

from __future__ import annotations

import random
from typing import Optional

from core.constants import DEFAULT_SIMULATED_LOSS_RATE


class PacketLossSimulator:
    def __init__(
        self,
        loss_rate: float = DEFAULT_SIMULATED_LOSS_RATE,
        random_generator: Optional[random.Random] = None,
    ) -> None:
        self.loss_rate = _validate_loss_rate(loss_rate)
        self.random = random_generator or random.Random()

    def should_drop(self) -> bool:
        return self.random.random() < self.loss_rate

    def set_loss_rate(self, loss_rate: float) -> None:
        self.loss_rate = _validate_loss_rate(loss_rate)


def _validate_loss_rate(loss_rate: float) -> float:
    number = float(loss_rate)
    if not 0.0 <= number <= 1.0:
        raise ValueError("loss_rate must be between 0.0 and 1.0")
    return number

