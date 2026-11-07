"""Phase 3 demo: full software pipeline rendered to a simulated LED panel.

    MBTA API -> MBTAClient -> normalized Departures -> StationManager
             -> DisplayEncoder -> SimulatedLEDDisplay (console)

Everything runs on Windows with no hardware. Run a scripted pass over all
configured stations (default):

    python -m src.phase3_console

Or flip stations yourself and re-render with fresh live data:

    python -m src.phase3_console --interactive
"""

from __future__ import annotations

import asyncio
import sys

from src.config import load_config
from src.display_driver import SimulatedLEDDisplay
from src.display_encoder import DisplayEncoder
from src.mbta_client import MBTAClient
from src.station_manager import StationManager, station_manager_from_config
from src.transit_service import fetch_station_departures

KEY_HELP = "Commands: n=next station, p=previous station, q=quit"


async def _render_current(
    client: MBTAClient,
    manager: StationManager,
    encoder: DisplayEncoder,
    display: SimulatedLEDDisplay,
) -> None:
    """Fetch live data for the selected station, encode it, and render."""
    station = manager.current_station()
    departures = (
        await fetch_station_departures(
            client, station, station_name=station.name, max_per_direction=2
        )
    ).departures
    # Use just the stop's plain name for the header (e.g. "Fenway").
    header_name = station.name.split(" - ")[0]
    frame = encoder.encode(header_name, departures)
    display.render(frame)


async def run_scripted() -> None:
    """Render every configured station once."""
    config = load_config()
    manager = station_manager_from_config(config)
    encoder = DisplayEncoder()
    display = SimulatedLEDDisplay()
    client = MBTAClient(api_key=config.mbta_api_key)
    try:
        for _ in range(manager.station_count):
            await _render_current(client, manager, encoder, display)
            print()
            manager.next_station()
    finally:
        await client.aclose()


async def run_interactive() -> None:
    """Change stations with the keyboard, re-rendering live data each time."""
    config = load_config()
    manager = station_manager_from_config(config)
    encoder = DisplayEncoder()
    display = SimulatedLEDDisplay(clear=True)
    client = MBTAClient(api_key=config.mbta_api_key)
    try:
        await _render_current(client, manager, encoder, display)
        print(KEY_HELP)
        while True:
            try:
                key = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if key == "q":
                break
            if key == "n":
                manager.next_station()
            elif key == "p":
                manager.previous_station()
            else:
                print("  (unknown command)")
                continue
            await _render_current(client, manager, encoder, display)
            print(KEY_HELP)
    finally:
        await client.aclose()


def main() -> None:
    if "--interactive" in sys.argv:
        asyncio.run(run_interactive())
    else:
        asyncio.run(run_scripted())


if __name__ == "__main__":
    main()
