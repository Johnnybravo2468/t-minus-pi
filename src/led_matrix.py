"""Pixel-accurate LED matrix simulation.

:class:`PixelMatrix` is a simple RGB pixel buffer with just enough drawing to
lay out text using the 5x7 font. It lets us preview exactly what a physical LED
matrix (e.g. 32x96) can show, on Windows, before buying hardware.

    normalized Departures  ->  render_station_board()  ->  PixelMatrix
                                                        ->  ASCII preview / PNG

This is the "simulated LED" side of the display driver split: a future
``RaspberryPiLEDDisplay`` would push the same kind of pixel buffer to the real
panel. The layout logic here is deliberately separate from any hardware.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from src.led_font import GLYPH_HEIGHT, GLYPH_WIDTH, glyph
from src.transit_model import Departure

RGB = Tuple[int, int, int]

WHITE: RGB = (235, 235, 235)
GREEN: RGB = (0, 200, 60)       # Green Line
RED: RGB = (220, 45, 40)        # Red Line
ORANGE: RGB = (255, 130, 0)     # Orange Line
BLUE: RGB = (0, 100, 255)       # Blue Line
PURPLE: RGB = (170, 70, 160)    # Commuter Rail
AMBER: RGB = (255, 176, 0)      # arrival minutes
CYAN: RGB = (0, 180, 200)       # section headers (INBOUND / OUTBOUND)
DIM: RGB = (90, 90, 90)

# Map an MBTA line to its brand color (LED-friendly shades).
LINE_COLORS = {
    "GREEN": GREEN,
    "RED": RED,
    "ORANGE": ORANGE,
    "BLUE": BLUE,
}


def color_for_line(line: str, branch: Optional[str] = None) -> RGB:
    """Return the brand color for a line name like 'Green Line' or 'CR-Worcester'."""
    text = (line or "").upper()
    for key, color in LINE_COLORS.items():
        if text.startswith(key):
            return color
    if text.startswith("CR-") or "COMMUTER" in text:
        return PURPLE
    return WHITE

# Character cell = glyph + 1px spacing, so 6px wide x 8px tall.
CELL_WIDTH = GLYPH_WIDTH + 1
CELL_HEIGHT = GLYPH_HEIGHT + 1


class PixelMatrix:
    """A width x height RGB pixel buffer."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._pixels: List[List[Optional[RGB]]] = [
            [None for _ in range(width)] for _ in range(height)
        ]

    def set_pixel(self, x: int, y: int, color: RGB) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self._pixels[y][x] = color

    def get_pixel(self, x: int, y: int) -> Optional[RGB]:
        return self._pixels[y][x]

    def draw_char(self, x: int, y: int, char: str, color: RGB) -> None:
        bitmap = glyph(char)
        for row in range(GLYPH_HEIGHT):
            for col in range(GLYPH_WIDTH):
                if bitmap[row][col]:
                    self.set_pixel(x + col, y + row, color)

    def draw_text(self, x: int, y: int, text: str, color: RGB) -> int:
        """Draw a string; returns the x position after the last character."""
        cursor = x
        for char in text:
            self.draw_char(cursor, y, char, color)
            cursor += CELL_WIDTH
        return cursor

    def draw_text_right(self, right_x: int, y: int, text: str, color: RGB) -> None:
        """Draw text ending (right-aligned) at ``right_x``."""
        width = len(text) * CELL_WIDTH - 1
        self.draw_text(right_x - width, y, text, color)

    def capacity(self) -> Tuple[int, int]:
        """Return (columns, rows) of characters that fit at 5x7."""
        return (self.width // CELL_WIDTH, self.height // CELL_HEIGHT)

    def to_ascii(self, on: str = "#", off: str = ".") -> str:
        lines = []
        for row in self._pixels:
            lines.append("".join(on if px else off for px in row))
        return "\n".join(lines)

    def to_png(self, path: str, scale: int = 8, background: RGB = (0, 0, 0)) -> None:
        """Save a scaled PNG preview. Requires Pillow (optional)."""
        from PIL import Image  # imported lazily so Pillow stays optional

        img = Image.new("RGB", (self.width, self.height), background)
        px = img.load()
        for y in range(self.height):
            for x in range(self.width):
                color = self._pixels[y][x]
                if color is not None:
                    px[x, y] = color
        img = img.resize((self.width * scale, self.height * scale), Image.NEAREST)
        img.save(path)


# Common MBTA destination words shortened so names fit a narrow panel.
_ABBREVIATIONS = {
    "SQUARE": "SQ",
    "STATION": "STA",
    "CENTER": "CTR",
    "STREET": "ST",
    "HEIGHTS": "HTS",
    "AVENUE": "AVE",
}


def _abbreviate(text: str, max_chars: int) -> str:
    text = text.upper()
    for full, short in _ABBREVIATIONS.items():
        text = text.replace(full, short)
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _status_color(status: str) -> RGB:
    """Amber for a degraded-but-showing board, red when data cannot be reached."""
    if status == "RATE LIMIT":
        return AMBER
    return RED


def render_station_board(
    matrix: PixelMatrix,
    station_name: str,
    route_label: str,
    departures: List[Departure],
    line_color: RGB = GREEN,
    status: str = "",
    clock: str = "",
) -> None:
    """Lay out a station board onto the matrix, adapting to the panel size.

    - Short panels (fewer than 7 text rows, e.g. 32x96) use a compact layout:
      a header row followed by one inbound and up to two outbound departures,
      each tagged ``I``/``O``.
    - Tall panels (7+ rows, e.g. two chained 64x64 panels = 64x128) use a
      sectioned layout with ``INBOUND`` / ``OUTBOUND`` headings and more rows.
    """
    cols, rows = matrix.capacity()
    right_x = matrix.width - 1

    inbound = sorted(
        [d for d in departures if d.direction == "Inbound"], key=lambda d: d.arrival_time
    )
    outbound = sorted(
        [d for d in departures if d.direction == "Outbound"], key=lambda d: d.arrival_time
    )

    # Row 0: station name in the line color. A clock, when given, replaces the
    # route label and is drawn in white. Otherwise the route label stays.
    right_text = clock or route_label
    right_color = WHITE if clock else line_color
    name_cols = cols - len(right_text) - (1 if right_text else 0)
    matrix.draw_text(0, 0, _abbreviate(station_name, max(name_cols, 1)), line_color)
    if right_text:
        matrix.draw_text_right(right_x, 0, right_text, right_color)

    # Tall panels leave row 1 blank between the header and the sections.
    # A fault code goes there. Short panels use that row for a departure.
    if status and rows >= 7:
        matrix.draw_text(0, CELL_HEIGHT, _abbreviate(status, cols), _status_color(status))

    if rows >= 7:
        _render_sections(matrix, cols, rows, right_x, inbound, outbound, line_color)
    else:
        _render_compact(matrix, cols, right_x, inbound, outbound, line_color)


def _render_compact(
    matrix: PixelMatrix,
    cols: int,
    right_x: int,
    inbound: List[Departure],
    outbound: List[Departure],
    line_color: RGB,
) -> None:
    dest_chars = cols - 3 - 1 - 2  # minutes(3) + gap + I/O tag(2)

    picks: List[Departure] = []
    if inbound:
        picks.append(inbound[0])
    picks.extend(outbound[:2])
    picks = picks[:3]

    for i, dep in enumerate(picks):
        y = (i + 1) * CELL_HEIGHT
        tag = "I" if dep.direction == "Inbound" else "O"
        matrix.draw_text(0, y, tag, line_color)
        matrix.draw_text(2 * CELL_WIDTH, y, _abbreviate(dep.destination, dest_chars), WHITE)
        matrix.draw_text_right(right_x, y, str(dep.minutes), AMBER)


def _render_sections(
    matrix: PixelMatrix,
    cols: int,
    rows: int,
    right_x: int,
    inbound: List[Departure],
    outbound: List[Departure],
    line_color: RGB,
) -> None:
    dest_chars = cols - 3 - 1  # minutes(3) + gap; no per-row tag needed

    # Split the rows below the header (and one blank) between the two sections.
    per_direction = max(1, (rows - 3) // 2)

    def draw_section(start_row: int, label: str, deps: List[Departure]) -> int:
        matrix.draw_text(0, start_row * CELL_HEIGHT, label, CYAN)
        row = start_row
        if not deps:
            row += 1
            matrix.draw_text(CELL_WIDTH, row * CELL_HEIGHT, "NO SERVICE", DIM)
            return row + 1
        for dep in deps[:per_direction]:
            row += 1
            y = row * CELL_HEIGHT
            matrix.draw_text(0, y, _abbreviate(dep.destination, dest_chars), WHITE)
            matrix.draw_text_right(right_x, y, str(dep.minutes), AMBER)
        return row + 1

    next_row = draw_section(2, "INBOUND", inbound)
    draw_section(next_row, "OUTBOUND", outbound)
