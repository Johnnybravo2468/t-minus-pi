"""Normalized transit data model.

This module is the single, hardware-agnostic representation of a departure
used by the rest of the application (station selection, display encoders,
console output, etc.).

Design goals:
- It knows nothing about the MBTA JSON:API format (that lives in
  ``mbta_client.py`` and the adapter in ``transit_service.py``).
- It knows nothing about displays, LEDs, or input hardware.
- The arrival time is the single authoritative value. ``minutes`` is always
  derived from it so it can never go stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# MBTA uses integer direction ids. Across the system, direction_id 0 is the
# "outbound" direction (e.g. West/South) and direction_id 1 is "inbound"
# (e.g. East/North). For Fenway on the Green Line D this maps to:
#   0 -> Outbound -> Riverside
#   1 -> Inbound  -> Union Square
DIRECTION_LABELS = {0: "Outbound", 1: "Inbound"}


def route_display(line: str, branch: Optional[str]) -> str:
    """Build a human-readable route label, e.g. ``Green Line (D)``."""
    if branch:
        return f"{line} ({branch})"
    return line


@dataclass
class Departure:
    """A single normalized upcoming departure/arrival.

    ``arrival_time`` must be a timezone-aware ``datetime`` and is treated as the
    authoritative prediction. ``minutes`` is computed on demand from it.
    """

    station_name: str
    line: str
    route_display: str
    direction: str          # "Inbound" / "Outbound"
    destination: str
    arrival_time: datetime  # timezone-aware; the authoritative value
    branch: Optional[str] = None
    status: Optional[str] = None
    trip_id: Optional[str] = None
    vehicle_id: Optional[str] = None

    @property
    def minutes(self) -> int:
        """Whole minutes from *now* until arrival (never negative).

        Derived from ``arrival_time`` every time it is read so it stays current
        even if the object was created seconds or minutes ago.
        """
        now = datetime.now(timezone.utc)
        seconds_remaining = (self.arrival_time - now).total_seconds()
        if seconds_remaining <= 0:
            return 0
        return int(seconds_remaining // 60)

    def countdown_label(self) -> str:
        """Short label suitable for a display, e.g. ``ARR`` or ``6 MIN``."""
        remaining = self.minutes
        if remaining <= 0:
            return "ARR"
        return f"{remaining} MIN"
