"""Module 21 - Location service.

The desktop prototype does not read GPS hardware. This service stores
manual or simulated coordinates and exposes a JSON-safe payload that can
be attached to status broadcasts or dashboard state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Optional

from core.constants import DEFAULT_LOCATION_LABEL


@dataclass(frozen=True, slots=True)
class Location:
    latitude: float
    longitude: float
    label: str = DEFAULT_LOCATION_LABEL
    timestamp: float = field(default_factory=time.time)

    def to_payload(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "label": self.label,
            "timestamp": self.timestamp,
        }


class LocationService:
    def __init__(self, initial_location: Optional[Location] = None) -> None:
        self._location = initial_location
        self._lock = threading.RLock()

    def set_location(
        self,
        latitude: float,
        longitude: float,
        label: str = DEFAULT_LOCATION_LABEL,
        timestamp: Optional[float] = None,
    ) -> Location:
        location = Location(
            latitude=_validate_latitude(latitude),
            longitude=_validate_longitude(longitude),
            label=label or DEFAULT_LOCATION_LABEL,
            timestamp=time.time() if timestamp is None else timestamp,
        )
        with self._lock:
            self._location = location
        return location

    def simulate_location(self, latitude: float, longitude: float, label: str = "SIMULATED") -> Location:
        return self.set_location(latitude=latitude, longitude=longitude, label=label)

    def clear_location(self) -> None:
        with self._lock:
            self._location = None

    def current_location(self) -> Optional[Location]:
        with self._lock:
            return self._location

    def current_payload(self) -> Optional[dict]:
        location = self.current_location()
        if location is None:
            return None
        return location.to_payload()


def _validate_latitude(value: float) -> float:
    number = float(value)
    if not -90.0 <= number <= 90.0:
        raise ValueError("latitude must be between -90 and 90")
    return number


def _validate_longitude(value: float) -> float:
    number = float(value)
    if not -180.0 <= number <= 180.0:
        raise ValueError("longitude must be between -180 and 180")
    return number

