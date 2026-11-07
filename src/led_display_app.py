"""Run the transit board on the LED matrix (hardware phase).

Pipeline:

    MBTA API -> MBTAClient -> Departures -> render_station_board -> PixelMatrix
             -> RaspberryPiLEDDisplay -> physical panels

On a Raspberry Pi with two chained 64x64 panels:

    sudo python -m src.led_display_app                # 128x64, refreshes live

With the Adafruit Triple Bonnet (#6358), add the 'regular' GPIO mapping:

    sudo python -m src.led_display_app --gpio-mapping regular

Off-Pi (for development), use the emulator drop-in:

    python -m src.led_display_app --emulator --once   # one frame
    python -m src.led_display_app --emulator          # live loop

Interactive mode drives the SAME live LED board with the keyboard through the
Phase 4 input seam (InputController -> AppController -> StationManager). This is
exactly where physical buttons will plug in later:

    python -m src.led_display_app --emulator --interactive

Flags:
    --emulator        use RGBMatrixEmulator instead of real hardware
    --once            render a single frame and exit
    --interval N      seconds between refreshes (default 15)
    --rotate          cycle to the next station on each refresh
    --interactive     control stations/mode from the keyboard
    --brightness N    panel brightness 1-100 (default 60)
"""

from __future__ import annotations

import argparse
import asyncio
from time import monotonic

from src.app_controller import AppController
from src.config import load_config
from src.display_encoder import compact_route_label
from src.input_controller import (
    BUTTON_3,
    NEXT_STATION,
    PREVIOUS_STATION,
    SimulatedInputController,
    TOGGLE,
)
from src.led_matrix import WHITE, PixelMatrix, color_for_line, render_station_board
from src.line_stations import build_all_line_stations
from src.mbta_client import MBTAClient
from src.rpi_led_display import RaspberryPiLEDDisplay
from src.station_manager import StationManager, _line_family, station_manager_from_config
from src.transit_service import fetch_station_departures

# Keyboard keys mapped to abstract input events (the same events physical
# buttons will emit through a WirelessInputController later).
KEY_TO_EVENT = {
    "n": NEXT_STATION,
    "p": PREVIOUS_STATION,
    "t": TOGGLE,
    "3": BUTTON_3,
}
KEY_HELP = "Keys: n=next station, p=previous station, t=next line, 3=button3, q=quit"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drive the LED transit board.")
    parser.add_argument("--emulator", action="store_true", help="use RGBMatrixEmulator")
    parser.add_argument("--once", action="store_true", help="render one frame and exit")
    parser.add_argument("--interval", type=int, default=15, help="seconds between refreshes")
    parser.add_argument("--rotate", action="store_true", help="cycle stations each refresh")
    parser.add_argument("--interactive", action="store_true", help="keyboard/button control")
    parser.add_argument("--brightness", type=int, default=60, help="brightness 1-100")
    # Panel/adapter geometry. Defaults suit the single Adafruit HAT/Bonnet.
    # For the Adafruit Triple Bonnet (#6358) use: --gpio-mapping regular
    parser.add_argument("--gpio-mapping", default="adafruit-hat",
                        help="rpi-rgb-led-matrix GPIO mapping (Triple Bonnet: 'regular')")
    parser.add_argument("--rows", type=int, default=64, help="pixel rows per panel")
    parser.add_argument("--cols", type=int, default=64, help="pixel cols per panel")
    parser.add_argument("--chain", type=int, default=2, help="panels chained per output")
    parser.add_argument("--parallel", type=int, default=1, help="parallel chains (outputs)")
    # The matrix library drops root->'daemon' after init by default, which stops
    # the process reading its venv under /home (breaks httpx/httpcore imports).
    # We keep privileges by default so the app works from a venv; opt back into
    # the more secure behavior with --drop-privileges.
    parser.add_argument("--drop-privileges", action="store_true",
                        help="drop to 'daemon' user after init (more secure; needs a system-readable venv)")
    # Load every station on every line straight from the MBTA API, grouped by
    # line (toggle cycles lines; next/previous move within a line).
    parser.add_argument("--all-lines", action="store_true",
                        help="load every station on every subway line from the MBTA API")
    parser.add_argument("--include-commuter", action="store_true",
                        help="with --all-lines, also include commuter rail")
    return parser.parse_args()


async def _build_manager(args: argparse.Namespace, config, client: MBTAClient) -> StationManager:
    if args.all_lines:
        stations = await build_all_line_stations(client, include_commuter=args.include_commuter)
        if stations:
            return StationManager(stations)
    return station_manager_from_config(config)


def _make_display(args: argparse.Namespace) -> RaspberryPiLEDDisplay:
    return RaspberryPiLEDDisplay(
        rows=args.rows,
        cols=args.cols,
        chain_length=args.chain,
        parallel=args.parallel,
        brightness=args.brightness,
        hardware_mapping=args.gpio_mapping,
        drop_privileges=args.drop_privileges,
        use_emulator=args.emulator,
    )


def route_label_for_station(station) -> str:
    """Corner label for the line being cycled, e.g. ``GREEN B``.

    Trunk stops fetch every Green branch, so the first departure no longer
    tells you which branch's station list you are on. The station's line does.
    """
    family = _line_family(station)
    if family.startswith("GREEN-") and len(family) == 7 and family[-1].isalpha():
        return f"GREEN {family[-1]}"
    return ""


def build_board(
    display: RaspberryPiLEDDisplay,
    station_name: str,
    departures,
    route_label: str = "",
) -> PixelMatrix:
    matrix = PixelMatrix(display.width, display.height)
    if not route_label and departures:
        route_label = compact_route_label(departures[0])
    if departures:
        line_color = color_for_line(departures[0].line, departures[0].branch)
    elif route_label.startswith("GREEN"):
        line_color = color_for_line("Green Line")
    else:
        line_color = WHITE
    render_station_board(matrix, station_name, route_label, departures, line_color=line_color)
    return matrix


# Short-lived cache of normalized departures per station. This prevents rapid
# key presses (e.g. toggling) from hammering the MBTA API and hitting its
# unauthenticated ~20 req/min limit (HTTP 429). It also lets us keep showing the
# last good board if a refresh fails.
CACHE_TTL_SECONDS = 10.0
_DEPARTURE_CACHE: dict = {}


async def _get_departures(client: MBTAClient, station, header_name: str):
    now = monotonic()
    cached = _DEPARTURE_CACHE.get(station.id)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    departures = await fetch_station_departures(
        client, station, station_name=header_name, max_per_direction=3
    )
    if departures:
        _DEPARTURE_CACHE[station.id] = (now, departures)
        return departures
    # Fetch returned nothing (e.g. rate-limited): reuse the last good board.
    return cached[1] if cached else departures


async def _render_current(
    client: MBTAClient, display: RaspberryPiLEDDisplay, manager: StationManager
) -> None:
    """Fetch live data for the selected station and push it to the panel."""
    station = manager.current_station()
    header_name = station.name.split(" - ")[0]
    departures = await _get_departures(client, station, header_name)
    display.render(
        build_board(
            display,
            header_name,
            departures,
            route_label=route_label_for_station(station),
        )
    )


async def _run_loop(args: argparse.Namespace) -> None:
    config = load_config()
    display = _make_display(args)
    client = MBTAClient(api_key=config.mbta_api_key)
    manager = await _build_manager(args, config, client)
    try:
        while True:
            await _render_current(client, display, manager)
            if args.once:
                break
            if args.rotate:
                manager.next_station()
            await asyncio.sleep(args.interval)
    finally:
        await client.aclose()
        display.clear()


async def _run_interactive(args: argparse.Namespace) -> None:
    config = load_config()
    display = _make_display(args)
    client = MBTAClient(api_key=config.mbta_api_key)
    manager = await _build_manager(args, config, client)
    controller = AppController(manager)
    inputs = SimulatedInputController()
    controller.connect(inputs)
    try:
        await _render_current(client, display, manager)
        print(KEY_HELP)
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
                print("  (unknown key)")
                continue
            # A physical button press would arrive the same way, via the
            # InputController -> AppController -> StationManager chain.
            inputs.emit(event)
            await _render_current(client, display, manager)
            print(f"  {manager.current_station().name}")
    finally:
        await client.aclose()
        display.clear()


def main() -> None:
    args = _parse_args()
    if args.interactive:
        asyncio.run(_run_interactive(args))
    else:
        asyncio.run(_run_loop(args))


if __name__ == "__main__":
    main()
