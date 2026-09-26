"""Phase 1 console runner.

Pipeline demonstrated here:

    MBTA API  ->  MBTAClient  ->  normalized Departures  ->  console output

Run it from the project root with:

    python -m src.phase1_console

It fetches live inbound/outbound predictions for Fenway on the Green Line (D)
and prints them. Everything here is testable on Windows with no hardware.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo

from src.config import DirectionConfig, RouteConfig, load_config
from src.mbta_client import MBTAClient
from src.transit_model import Departure
from src.transit_service import fetch_station_departures

# Timezone used for the "Updated" line. The arrival times themselves are already
# timezone-aware and come straight from the API.
DISPLAY_TZ = ZoneInfo("America/New_York")

# The first station of interest. This reuses the repository's existing
# RouteConfig model. In a later phase this will move into the station manager /
# configuration file; for Phase 1 it is defined here so the demo is self-contained.
FENWAY_GREEN_D = RouteConfig(
    id="fenway_green_d",
    type="subway",
    route_id="Green-D",
    stop_id="place-fenwy",
    name="Fenway - Green Line (D)",
    directions=[
        DirectionConfig(direction_id=1, headsign="Union Square (Inbound)"),
        DirectionConfig(direction_id=0, headsign="Riverside (Outbound)"),
    ],
)

STATION_TITLE = "FENWAY \u2014 GREEN LINE (D)"


def _format_departures(departures: List[Departure]) -> str:
    """Render normalized departures into the Phase 1 console layout."""
    lines: List[str] = []
    separator = "=" * 32
    lines.append(separator)
    lines.append(STATION_TITLE)
    lines.append(separator)

    for direction in ("Inbound", "Outbound"):
        in_direction = [d for d in departures if d.direction == direction]
        in_direction.sort(key=lambda d: d.arrival_time)

        lines.append("")
        lines.append(direction.upper())
        if not in_direction:
            lines.append("  (no upcoming departures)")
            continue
        for dep in in_direction:
            minutes_label = f"{dep.minutes} min"
            lines.append(f"{dep.destination:<18}{minutes_label:>7}")

    lines.append("")
    lines.append(f"Updated: {_format_clock(datetime.now(DISPLAY_TZ))}")
    return "\n".join(lines)


def _format_clock(now: datetime) -> str:
    """12-hour time like ``7:28 PM`` (no platform-specific strftime codes)."""
    hour_12 = now.hour % 12 or 12
    meridiem = "AM" if now.hour < 12 else "PM"
    return f"{hour_12}:{now.minute:02d} {meridiem}"


async def _run() -> None:
    config = load_config()
    client = MBTAClient(api_key=config.mbta_api_key)
    try:
        departures = await fetch_station_departures(
            client, FENWAY_GREEN_D, station_name="Fenway", max_per_direction=3
        )
    finally:
        await client.aclose()

    print(_format_departures(departures))


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
