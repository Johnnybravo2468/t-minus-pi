"""Display encoder (Phase 3).

Converts normalized :class:`~src.transit_model.Departure` data into a
display-agnostic *frame*: a fixed-width grid of text rows.

This is the boundary described in the architecture:

    Departure data  ->  DisplayEncoder  ->  DisplayFrame  ->  (a display driver)

The encoder knows how to *lay out* a station board. It deliberately knows
nothing about the physical LED matrix (pixels, wiring, brightness). A display
driver takes the frame and renders it (Phase 3 uses a simulated LED display;
Phase 5 will add a real Raspberry Pi LED driver). Because both sides share the
simple :class:`DisplayFrame`, either side can change independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.transit_model import Departure

# Default character width of the board. Think of this as the number of columns
# on the panel; the real LED matrix driver can pick its own width later.
DEFAULT_WIDTH = 46
# How many columns are reserved on the right for the minutes value.
MINUTES_COLUMN = 4


@dataclass
class DisplayFrame:
    """A rendered board: a list of rows, every row exactly ``width`` chars.

    This is the neutral hand-off format between the encoder and any display
    driver. It contains only text, no MBTA or hardware concepts.
    """

    width: int
    rows: List[str]

    def __post_init__(self) -> None:
        # Guarantee every row is exactly `width` characters so downstream
        # drivers (console box, LED grid) can rely on a clean rectangle.
        self.rows = [self._fit(row) for row in self.rows]

    def _fit(self, row: str) -> str:
        if len(row) > self.width:
            return row[: self.width]
        return row.ljust(self.width)

    def as_text(self) -> str:
        return "\n".join(self.rows)


def compact_route_label(departure: Departure) -> str:
    """Turn a route into a short header label, e.g. ``GREEN D``."""
    line = departure.line.replace(" Line", "").strip()
    if departure.branch:
        return f"{line} {departure.branch}".upper()
    return line.upper()


class DisplayEncoder:
    """Lays out a single station's departures into a :class:`DisplayFrame`."""

    def __init__(self, width: int = DEFAULT_WIDTH, max_per_direction: int = 2):
        self.width = width
        self.max_per_direction = max_per_direction

    def _header_row(self, station_name: str, route_label: str) -> str:
        left = station_name.upper()
        right = route_label
        space = self.width - len(right)
        if space < 1:
            # Route label alone is too wide; just show it truncated.
            return right[: self.width]
        return f"{left[:space - 1]:<{space}}{right}"

    def _departure_row(self, departure: Departure) -> str:
        minutes = str(departure.minutes)
        dest_width = self.width - MINUTES_COLUMN
        destination = departure.destination.upper()[:dest_width]
        return f"{destination:<{dest_width}}{minutes:>{MINUTES_COLUMN}}"

    def _direction_block(
        self, label: str, departures: List[Departure]
    ) -> List[str]:
        rows = [label.upper()]
        chosen = sorted(departures, key=lambda d: d.arrival_time)[
            : self.max_per_direction
        ]
        if not chosen:
            rows.append("  (no service)")
            return rows
        rows.extend(self._departure_row(dep) for dep in chosen)
        return rows

    def encode(
        self,
        station_name: str,
        departures: List[Departure],
        route_label: Optional[str] = None,
    ) -> DisplayFrame:
        """Build the frame for one station from its normalized departures."""
        if route_label is None:
            route_label = compact_route_label(departures[0]) if departures else ""

        inbound = [d for d in departures if d.direction == "Inbound"]
        outbound = [d for d in departures if d.direction == "Outbound"]

        rows: List[str] = []
        rows.append(self._header_row(station_name, route_label))
        rows.append("")
        rows.extend(self._direction_block("Inbound", inbound))
        rows.append("")
        rows.extend(self._direction_block("Outbound", outbound))

        return DisplayFrame(width=self.width, rows=rows)
