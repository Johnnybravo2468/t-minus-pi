"""Phase 2 demo: station selection driven by abstract events (no hardware).

This proves the station-selection state machine works on Windows before any
wireless I/O exists. Abstract events like ``NEXT_STATION`` / ``TOGGLE`` are
mapped to :class:`StationManager` operations here (this mapping is what a real
``InputController`` will feed in Phase 4 — it stays outside the manager so it
can be reconfigured later).

Run a scripted simulation (default):

    python -m src.phase2_console

Or drive it yourself from the keyboard:

    python -m src.phase2_console --interactive
"""

from __future__ import annotations

import asyncio
import sys
from typing import Callable, Dict, List

from src.config import load_config
from src.mbta_client import MBTAClient
from src.station_manager import StationManager, station_manager_from_config
from src.transit_service import fetch_station_departures

# Abstract event -> what it does to the manager. Editable/config-driven later.
EVENT_ACTIONS: Dict[str, Callable[[StationManager], object]] = {
    "NEXT_STATION": lambda m: m.next_station(),
    "PREVIOUS_STATION": lambda m: m.previous_station(),
    "TOGGLE": lambda m: m.toggle_mode(),
    # BUTTON_3 is a placeholder "confirm / select current" action for now.
    "BUTTON_3": lambda m: m.current_station(),
}

# Keyboard shortcuts for interactive mode.
KEY_TO_EVENT = {
    "n": "NEXT_STATION",
    "p": "PREVIOUS_STATION",
    "t": "TOGGLE",
    "3": "BUTTON_3",
}


def apply_event(manager: StationManager, event: str) -> None:
    """Apply one abstract event to the manager, ignoring unknown events."""
    action = EVENT_ACTIONS.get(event)
    if action is None:
        print(f"(ignored unknown event: {event})")
        return
    action(manager)


def _state_line(manager: StationManager) -> str:
    station = manager.current_station()
    return (
        f"[{manager.mode.value}] "
        f"station {manager.current_index + 1}/{manager.station_count}: {station.name}"
    )


def run_simulation(manager: StationManager) -> None:
    """Feed a fixed sequence of events and print the resulting state each time."""
    events: List[str] = [
        "NEXT_STATION",
        "NEXT_STATION",
        "PREVIOUS_STATION",
        "TOGGLE",
        "BUTTON_3",
        "TOGGLE",
    ]

    print("Initial state:")
    print("  " + _state_line(manager))
    print()
    for event in events:
        apply_event(manager, event)
        print(f"{event:<16} -> {_state_line(manager)}")


async def _show_live_departures(manager: StationManager) -> None:
    """Fetch live departures for the currently selected station (Phase 1 reuse)."""
    config = load_config()
    client = MBTAClient(api_key=config.mbta_api_key)
    try:
        station = manager.current_station()
        departures = (
            await fetch_station_departures(
                client, station, station_name=station.name, max_per_direction=2
            )
        ).departures
    finally:
        await client.aclose()

    print()
    print(f"Live departures for selected station: {station.name}")
    if not departures:
        print("  (no upcoming departures)")
        return
    for dep in sorted(departures, key=lambda d: d.arrival_time):
        print(f"  {dep.direction:<9} {dep.destination:<16} {dep.minutes:>3} min")


def run_interactive(manager: StationManager) -> None:
    """Drive the manager from the keyboard using simple typed commands."""
    print("Interactive mode. Commands: n=next, p=previous, t=toggle, 3=button3, q=quit")
    print("  " + _state_line(manager))
    while True:
        try:
            key = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if key == "q":
            break
        event = KEY_TO_EVENT.get(key)
        if event is None:
            print("  (unknown command)")
            continue
        apply_event(manager, event)
        print("  " + _state_line(manager))


def main() -> None:
    manager = station_manager_from_config()
    if "--interactive" in sys.argv:
        run_interactive(manager)
        return
    run_simulation(manager)
    asyncio.run(_show_live_departures(manager))


if __name__ == "__main__":
    main()
