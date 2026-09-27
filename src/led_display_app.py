"""Run the transit board on the LED matrix (hardware phase, display only).

Pipeline:

    MBTA API -> MBTAClient -> Departures -> render_station_board -> PixelMatrix
             -> RaspberryPiLEDDisplay -> physical panels

On a Raspberry Pi with two chained 64x64 panels:

    sudo python -m src.led_display_app                # 128x64, refreshes live

Off-Pi (for development), use the emulator drop-in:

    python -m src.led_display_app --emulator --once   # one frame
    python -m src.led_display_app --emulator          # live loop

Flags:
    --emulator        use RGBMatrixEmulator instead of real hardware
    --once            render a single frame and exit
    --interval N      seconds between refreshes (default 15)
    --rotate          cycle to the next station on each refresh
    --brightness N    panel brightness 1-100 (default 60)
"""

from __future__ import annotations

import argparse
import asyncio

from src.config import load_config
from src.display_encoder import compact_route_label
from src.led_matrix import PixelMatrix, render_station_board
from src.mbta_client import MBTAClient
from src.rpi_led_display import RaspberryPiLEDDisplay
from src.station_manager import station_manager_from_config
from src.transit_service import fetch_station_departures


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drive the LED transit board.")
    parser.add_argument("--emulator", action="store_true", help="use RGBMatrixEmulator")
    parser.add_argument("--once", action="store_true", help="render one frame and exit")
    parser.add_argument("--interval", type=int, default=15, help="seconds between refreshes")
    parser.add_argument("--rotate", action="store_true", help="cycle stations each refresh")
    parser.add_argument("--brightness", type=int, default=60, help="brightness 1-100")
    return parser.parse_args()


def build_board(display: RaspberryPiLEDDisplay, station_name: str, departures) -> PixelMatrix:
    matrix = PixelMatrix(display.width, display.height)
    route_label = compact_route_label(departures[0]) if departures else ""
    render_station_board(matrix, station_name, route_label, departures)
    return matrix


async def _run(args: argparse.Namespace) -> None:
    config = load_config()
    manager = station_manager_from_config(config)
    display = RaspberryPiLEDDisplay(
        brightness=args.brightness, use_emulator=args.emulator
    )
    client = MBTAClient(api_key=config.mbta_api_key)
    try:
        while True:
            station = manager.current_station()
            header_name = station.name.split(" - ")[0]
            departures = await fetch_station_departures(
                client, station, station_name=header_name, max_per_direction=3
            )
            board = build_board(display, header_name, departures)
            display.render(board)

            if args.once:
                break
            if args.rotate:
                manager.next_station()
            await asyncio.sleep(args.interval)
    finally:
        await client.aclose()
        display.clear()


def main() -> None:
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
