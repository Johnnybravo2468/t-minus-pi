"""Feasibility test: can the transit board be shown on a 32x96 LED matrix?

It renders a real station board at actual pixel dimensions using the 5x7 LED
font, prints an ASCII pixel preview, optionally saves a scaled PNG, and reports
how much text fits.

    python -m src.led_feasibility                 # live data (Fenway)
    python -m src.led_feasibility --sample        # no network, fixed data
    python -m src.led_feasibility --png board.png # also save a PNG (needs Pillow)

Matrix geometry is height x width in pixels; a "32x96" panel is 32 tall, 96 wide.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.config import load_config
from src.led_matrix import (
    CELL_HEIGHT,
    CELL_WIDTH,
    WHITE,
    PixelMatrix,
    color_for_line,
    render_station_board,
)
from src.mbta_client import MBTAClient
from src.station_manager import DEFAULT_STATIONS
from src.transit_model import Departure
from src.transit_service import fetch_station_departures

MATRIX_HEIGHT = 32
MATRIX_WIDTH = 96


def _sample_departures() -> List[Departure]:
    now = datetime.now(timezone.utc)

    def dep(direction: str, dest: str, mins: int) -> Departure:
        return Departure(
            station_name="Fenway",
            line="Green Line",
            route_display="Green Line (D)",
            direction=direction,
            destination=dest,
            arrival_time=now + timedelta(minutes=mins),
            branch="D",
        )

    return [
        dep("Inbound", "Union Square", 3),
        dep("Inbound", "Union Square", 15),
        dep("Outbound", "Riverside", 7),
        dep("Outbound", "Riverside", 21),
    ]


async def _live_departures() -> List[Departure]:
    config = load_config()
    client = MBTAClient(api_key=config.mbta_api_key)
    station = DEFAULT_STATIONS[0]  # Fenway - Green Line (D)
    try:
        return (
            await fetch_station_departures(
                client, station, station_name="Fenway", max_per_direction=3
            )
        ).departures
    finally:
        await client.aclose()


def _print_metrics(matrix: PixelMatrix) -> None:
    cols, rows = matrix.capacity()
    print("=" * 60)
    print(f"LED matrix feasibility: {matrix.height} x {matrix.width} px")
    print("=" * 60)
    print(f"Font: 5x7 (character cell {CELL_WIDTH}x{CELL_HEIGHT} px incl. spacing)")
    print(f"Text capacity: {cols} columns x {rows} rows = {cols * rows} characters")
    print(f"  -> per line you can fit ~{cols} characters")
    print(f"  -> you can stack {rows} lines of text")
    print()


def _ruler(width: int) -> str:
    return "".join(str((i // 10) % 10) if i % 10 == 0 else "." for i in range(width))


def build_board(departures: List[Departure], width: int, height: int) -> PixelMatrix:
    matrix = PixelMatrix(width, height)
    # A wider panel has room for a fuller route label.
    route_label = "GREEN LINE D" if width >= 110 else "GRN D"
    line_color = (
        color_for_line(departures[0].line, departures[0].branch) if departures else WHITE
    )
    render_station_board(matrix, "Fenway", route_label, departures, line_color=line_color)
    return matrix


def _int_arg(name: str, default: int) -> int:
    if name in sys.argv:
        idx = sys.argv.index(name)
        if idx + 1 < len(sys.argv):
            return int(sys.argv[idx + 1])
    return default


def main() -> None:
    use_sample = "--sample" in sys.argv
    width = _int_arg("--width", MATRIX_WIDTH)
    height = _int_arg("--height", MATRIX_HEIGHT)
    png_path: Optional[str] = None
    if "--png" in sys.argv:
        idx = sys.argv.index("--png")
        png_path = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "led_board.png"

    departures = _sample_departures() if use_sample else asyncio.run(_live_departures())

    matrix = build_board(departures, width, height)

    _print_metrics(matrix)
    print("Pixel preview (each '#' = one lit LED, '.' = off):")
    print("   " + _ruler(matrix.width))
    for i, line in enumerate(matrix.to_ascii().splitlines()):
        print(f"{i:2d} {line}")
    print()

    if png_path:
        try:
            matrix.to_png(png_path, scale=8)
            print(f"Saved scaled PNG preview to: {png_path}")
        except ImportError:
            print("PNG output needs Pillow. Install with: pip install pillow")

    cols, rows = matrix.capacity()
    print()
    print(f"Verdict: {matrix.height}x{matrix.width} fits {cols} chars x {rows} rows "
          "at 5x7. Long names auto-abbreviate; use RGB color to code")
    print("line/direction, and scroll for anything longer.")


if __name__ == "__main__":
    main()
