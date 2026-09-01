"""Latency and jitter simulation for Module 22."""

from __future__ import annotations

import random
from typing import Optional

from core.constants import DEFAULT_SIMULATED_DELAY_SECONDS, DEFAULT_SIMULATED_JITTER_SECONDS


class LatencySimulator:
    def __init__(
        self,
        base_delay_seconds: float = DEFAULT_SIMULATED_DELAY_SECONDS,
        jitter_seconds: float = DEFAULT_SIMULATED_JITTER_SECONDS,
        random_generator: Optional[random.Random] = None,
    ) -> None:
        self.base_delay_seconds = _validate_non_negative(base_delay_seconds, "base_delay_seconds")
        self.jitter_seconds = _validate_non_negative(jitter_seconds, "jitter_seconds")
        self.random = random_generator or random.Random()

    def delay_seconds(self) -> float:
        if self.jitter_seconds == 0:
            return self.base_delay_seconds
        jitter = self.random.uniform(-self.jitter_seconds, self.jitter_seconds)
        return max(0.0, self.base_delay_seconds + jitter)

    def set_delay(self, base_delay_seconds: float, jitter_seconds: float = 0.0) -> None:
        self.base_delay_seconds = _validate_non_negative(base_delay_seconds, "base_delay_seconds")
        self.jitter_seconds = _validate_non_negative(jitter_seconds, "jitter_seconds")


def _validate_non_negative(value: float, name: str) -> float:
    number = float(value)
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number

