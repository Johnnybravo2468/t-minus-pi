"""Phase 4 demo: drive the whole app through the input seam (no hardware).

    SimulatedInputController --emit--> AppController --> StationManager
                                                     --> (optional) display

Default: a scripted burst of simulated button events, printing the resulting
state. This tests the entire state machine with no network and no hardware:

    python -m src.phase4_console

Interactive: keyboard keys become button events and the selected station is
rendered live to the simulated LED panel (Phases 1-4 together):

    python -m src.phase4_console --interactive
"""

from __future__ import annotations

import asyncio
import sys

from src.app_controller import AppController
from src.config import load_config
from src.display_driver import SimulatedLEDDisplay
from src.display_encoder import DisplayEncoder
from src.input_controller import (
    BUTTON_3,
    NEXT_STATION,
    PREVIOUS_STATION,
    SimulatedInputController,
    TOGGLE,
)
from src.mbta_client import MBTAClient
from src.station_manager import StationManager, station_manager_from_config
from src.transit_service import fetch_station_departures

KEY_TO_EVENT = {
    "n": NEXT_STATION,
    "p": PREVIOUS_STATION,
    "t": TOGGLE,
    "3": BUTTON_3,
}
KEY_HELP = "Commands: n=next, p=previous, t=toggle, 3=button3, q=quit"


def _state_line(manager: StationManager) -> str:
    station = manager.current_station()
    return (
        f"[{manager.mode.value}] "
        f"station {manager.current_index + 1}/{manager.station_count}: {station.name}"
    )


def run_scripted() -> None:
    manager = station_manager_from_config()

    def on_change(event: str, m: StationManager) -> None:
        print(f"{event:<16} -> {_state_line(m)}")

    controller = AppController(manager, on_change=on_change)
    inputs = SimulatedInputController()
    controller.connect(inputs)

    print("Initial: " + _state_line(manager))
    for event in [
        NEXT_STATION,
        NEXT_STATION,
        TOGGLE,
        PREVIOUS_STATION,
        BUTTON_3,
        TOGGLE,
        "NONSENSE",  # unknown event is safely ignored
    ]:
        inputs.emit(event)


async def _render_current(
    client: MBTAClient,
    manager: StationManager,
    encoder: DisplayEncoder,
    display: SimulatedLEDDisplay,
) -> None:
    station = manager.current_station()
    departures = await fetch_station_departures(
        client, station, station_name=station.name, max_per_direction=2
    )
    header_name = station.name.split(" - ")[0]
    display.render(encoder.encode(header_name, departures))


async def run_interactive() -> None:
    config = load_config()
    manager = station_manager_from_config(config)
    controller = AppController(manager)
    inputs = SimulatedInputController()
    controller.connect(inputs)

    encoder = DisplayEncoder()
    display = SimulatedLEDDisplay(clear=True)
    client = MBTAClient(api_key=config.mbta_api_key)
    try:
        await _render_current(client, manager, encoder, display)
        print(f"{_state_line(manager)}\n{KEY_HELP}")
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
            # A real button press would arrive the same way via _dispatch.
            inputs.emit(event)
            await _render_current(client, manager, encoder, display)
            print(f"{_state_line(manager)}\n{KEY_HELP}")
    finally:
        await client.aclose()


def main() -> None:
    if "--interactive" in sys.argv:
        asyncio.run(run_interactive())
    else:
        run_scripted()


if __name__ == "__main__":
    main()
