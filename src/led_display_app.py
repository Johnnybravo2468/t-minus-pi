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

Interactive mode still refreshes the station currently on screen every
``--interval`` seconds. Keys only change which station that is.

The same controls are served on the local network for a phone. The address
does not change when the Pi's numeric address does:

    http://t-minus-pi.local:8080

Flags:
    --emulator        use RGBMatrixEmulator instead of real hardware
    --once            render a single frame and exit
    --interval N      seconds between refreshes (default 15)
    --rotate          cycle to the next station on each refresh
    --interactive     control stations/mode from the keyboard
    --brightness N    panel brightness 1-100 (default 60)
    --web-port N      phone button page port (default 8080)
    --no-web          do not serve the phone button page
"""

from __future__ import annotations

import argparse
import asyncio
import queue
import threading
from datetime import datetime
from time import monotonic

from src.app_controller import AppController
from src.config import load_config
from src.diagnostics import has_default_route, panel_status
from src.display_encoder import compact_route_label
from src.input_controller import (
    BUS_MODE,
    BUTTON_3,
    NEXT_STATION,
    PREVIOUS_STATION,
    SimulatedInputController,
    TOGGLE,
)
from src.led_matrix import WHITE, PixelMatrix, color_for_line, render_station_board
from src.line_stations import build_all_line_stations, build_bus_stations
from src.mbta_client import MBTAClient
from src.phone_control import (
    PhoneControl,
    advertise_stable_name,
    phone_url,
    preferred_lan_ip,
    start_phone_server,
)
from src.rpi_led_display import RaspberryPiLEDDisplay
from src.station_manager import StationManager, _line_family, station_manager_from_config
from src.transit_service import StationFetch, fetch_station_departures

# Keyboard keys mapped to abstract input events (the same events physical
# buttons will emit through a WirelessInputController later).
KEY_TO_EVENT = {
    "n": NEXT_STATION,
    "p": PREVIOUS_STATION,
    "t": TOGGLE,
    "b": BUS_MODE,
    "3": BUTTON_3,
}
KEY_HELP = (
    "Keys: n=next station, p=previous station, t=next line, b=bus routes, "
    "3=button3, q=quit\n"
    "The station on screen refreshes on its own. Keys only change the station."
)


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
    parser.add_argument("--web-port", type=int, default=8080,
                        help="port for the phone button page")
    parser.add_argument("--no-web", action="store_true",
                        help="do not serve the phone button page")
    return parser.parse_args()


# Green-D Fenway. Startup always lands here when that stop is in the list.
FENWAY_STOP_ID = "place-fenwy"
FENWAY_LINE = "GREEN-D"


def _start_at_fenway(manager: StationManager) -> StationManager:
    """Open on Fenway when it is loaded. Otherwise keep the first station."""
    manager.select_stop(FENWAY_STOP_ID, FENWAY_LINE)
    return manager


async def _build_manager(args: argparse.Namespace, config, client: MBTAClient) -> StationManager:
    if args.all_lines:
        stations = await build_all_line_stations(client, include_commuter=args.include_commuter)
        if stations:
            return _start_at_fenway(StationManager(stations))
    base = station_manager_from_config(config)
    return _start_at_fenway(StationManager(list(base._stations) + build_bus_stations()))


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


def station_header_name(station) -> str:
    """Station name for the header.

    Every Green stop is labeled with the branch currently being cycled, so
    Fenway reads ``Fenway (D)`` and the D copy of a trunk stop reads
    ``Park Street (D)``. Switching to the B list at that same stop reads
    ``Park Street (B)``. Other lines keep the plain station name.
    """
    family = _line_family(station)
    if family.startswith("BUS-"):
        # Keep the full stop name. Bus stops can already contain " - ".
        return f"{station.name} ({family.split('-', 1)[1]})"
    plain = station.name.split(" - ")[0]
    if family.startswith("GREEN-") and len(family) == 7 and family[-1].isalpha():
        return f"{plain} ({family[-1]})"
    return plain


def format_clock(now: datetime | None = None) -> str:
    """12-hour local time for the header corner, e.g. ``1:05 PM``.

    An aware ``now`` is shown in its own zone. When ``now`` is omitted, the
    clock uses the Pi's local time.
    """
    current = now if now is not None else datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    hour = current.hour % 12 or 12
    suffix = "AM" if current.hour < 12 else "PM"
    return f"{hour}:{current.minute:02d} {suffix}"


def build_board(
    display: RaspberryPiLEDDisplay,
    station_name: str,
    departures,
    route_label: str = "",
    status: str = "",
    clock: str = "",
    line_hint: str = "",
) -> PixelMatrix:
    matrix = PixelMatrix(display.width, display.height)
    if not clock and not route_label and departures:
        route_label = compact_route_label(departures[0])
    # Bus stop names stay white. Rail names keep the line color.
    if (line_hint or "").startswith("BUS"):
        line_color = WHITE
    elif departures:
        line_color = color_for_line(departures[0].line, departures[0].branch)
    elif line_hint:
        line_color = color_for_line(line_hint)
    elif route_label.startswith("GREEN"):
        line_color = color_for_line("Green Line")
    else:
        line_color = WHITE
    render_station_board(
        matrix,
        station_name,
        route_label,
        departures,
        line_color=line_color,
        status=status,
        clock=clock,
    )
    return matrix


# Short-lived cache of normalized departures per station. This prevents rapid
# key presses (e.g. toggling) from hammering the MBTA API and hitting its
# unauthenticated ~20 req/min limit (HTTP 429). It also lets us keep showing the
# last good board if a refresh fails.
CACHE_TTL_SECONDS = 10.0
_DEPARTURE_CACHE: dict = {}
# Fault code for the most recent refresh. Empty when the board is healthy.
_LAST_STATUS = ""
_PRINTED_STATUS: str | None = None
# Phone page state. None until the local web server starts.
_PHONE: PhoneControl | None = None


def _set_status(status: str) -> None:
    """Remember the code drawn on the panel, and print it once when it changes."""
    global _LAST_STATUS, _PRINTED_STATUS
    _LAST_STATUS = status
    if status == _PRINTED_STATUS:
        return
    _PRINTED_STATUS = status
    if status:
        print(f"[diag] {status}", flush=True)


async def _get_departures(client: MBTAClient, station, header_name: str):
    now = monotonic()
    cached = _DEPARTURE_CACHE.get(station.id)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        _set_status("")
        return cached[1]
    fetched = await fetch_station_departures(
        client, station, station_name=header_name, max_per_direction=3
    )
    # Tests and older callers may still return a bare list.
    if isinstance(fetched, StationFetch):
        departures = fetched.departures
        error = fetched.error
    else:
        departures = fetched
        error = None
    if departures:
        _DEPARTURE_CACHE[station.id] = (now, departures)
        _set_status("")
        return departures
    # A failed refresh keeps the last good board. The status row says why.
    _set_status(panel_status(error, has_default_route()))
    return cached[1] if cached else departures


async def _render_current(
    client: MBTAClient, display: RaspberryPiLEDDisplay, manager: StationManager
) -> None:
    """Fetch live data for the selected station and push it to the panel."""
    station = manager.current_station()
    header_name = station_header_name(station)
    departures = await _get_departures(client, station, header_name.split(" (")[0])
    display.render(
        build_board(
            display,
            header_name,
            departures,
            status=_LAST_STATUS,
            clock=format_clock(),
            line_hint=_line_family(station),
        )
    )
    _publish_phone(manager)


def _publish_phone(manager: StationManager) -> None:
    phone = _PHONE
    if phone is None:
        return
    station = manager.current_station()
    phone.update(
        station_header_name(station),
        manager.current_line(),
        _LAST_STATUS,
        manager.service_mode(),
    )


def _start_phone(args: argparse.Namespace, commands: queue.Queue) -> None:
    """Serve the button page on the LAN and print the address a phone can open."""
    global _PHONE
    if args.no_web:
        return
    control = PhoneControl(commands)
    server = start_phone_server(control, port=args.web_port)
    if server is None:
        return
    _PHONE = control
    ip = preferred_lan_ip()
    announced = bool(ip) and advertise_stable_name(args.web_port, ip)
    print(f"Phone controls: {phone_url(args.web_port)}", flush=True)
    if ip and not announced:
        print(f"Current address: http://{ip}:{args.web_port}", flush=True)
    elif not ip:
        print("No network address found, so the phone page is not reachable yet.", flush=True)


async def _run_loop(args: argparse.Namespace) -> None:
    config = load_config()
    display = _make_display(args)
    client = MBTAClient(api_key=config.mbta_api_key)
    manager = await _build_manager(args, config, client)
    commands: queue.Queue = queue.Queue()
    _start_phone(args, commands)
    controller = AppController(manager)
    inputs = SimulatedInputController()
    controller.connect(inputs)
    try:
        await _render_current(client, display, manager)
        while True:
            if args.once:
                break
            try:
                line = await _read_command(commands, args.interval)
            except EOFError:
                break
            if line:
                action = apply_interactive_key(str(line).strip().lower(), inputs)
                if action == "quit":
                    break
                if action != "unknown":
                    await _render_current(client, display, manager)
                continue
            if args.rotate:
                manager.next_station()
            await _render_current(client, display, manager)
    finally:
        await client.aclose()
        display.clear()


def apply_interactive_key(key: str, inputs: SimulatedInputController) -> str:
    """Apply one typed command. Returns ``quit``, ``unknown``, or ``ok``."""
    if key == "q":
        return "quit"
    event = KEY_TO_EVENT.get(key)
    if event is None:
        return "unknown"
    # A physical button press arrives the same way, via
    # InputController -> AppController -> StationManager.
    inputs.emit(event)
    return "ok"


def _spawn_command_reader(lines: queue.Queue) -> None:
    """Read keyboard lines on a daemon thread so the panel can refresh meanwhile."""

    def _read() -> None:
        while True:
            try:
                lines.put(input("> "))
            except (EOFError, KeyboardInterrupt):
                lines.put(None)
                return

    threading.Thread(target=_read, name="led-keyboard", daemon=True).start()


async def _read_command(lines: queue.Queue, interval: float):
    """Return the next typed line, or None when ``interval`` seconds pass."""
    try:
        line = await asyncio.to_thread(lines.get, True, interval)
    except queue.Empty:
        return None
    if line is None:
        raise EOFError
    return line


async def _interactive_loop(manager, inputs, interval: float, read_line, render) -> None:
    """Refresh the current station on a timer, and change it when a key arrives."""
    print(KEY_HELP)
    while True:
        try:
            line = await read_line(interval)
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if line is None:
            await render()
            continue
        action = apply_interactive_key(line.strip().lower(), inputs)
        if action == "quit":
            return
        if action == "unknown":
            print("  (unknown key)")
            continue
        await render()
        print(f"  {manager.current_station().name}")


async def _run_interactive(args: argparse.Namespace) -> None:
    config = load_config()
    display = _make_display(args)
    client = MBTAClient(api_key=config.mbta_api_key)
    manager = await _build_manager(args, config, client)
    controller = AppController(manager)
    inputs = SimulatedInputController()
    controller.connect(inputs)
    commands: queue.Queue = queue.Queue()
    _spawn_command_reader(commands)
    _start_phone(args, commands)

    async def read_line(interval: float):
        return await _read_command(commands, interval)

    async def render() -> None:
        await _render_current(client, display, manager)

    try:
        await render()
        await _interactive_loop(manager, inputs, args.interval, read_line, render)
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
