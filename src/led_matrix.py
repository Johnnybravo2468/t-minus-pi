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
AMBER: RGB = (255, 176, 0)      # arrival minutes
DIM: RGB = (90, 90, 90)

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


def render_station_board(
    matrix: PixelMatrix,
    station_name: str,
    route_label: str,
    departures: List[Departure],
    line_color: RGB = GREEN,
) -> None:
    """Lay out a compact station board onto the matrix.

    Layout for a 32x96 panel (16 cols x 4 rows at 5x7):
        row 0: station name (left)      route label (right)
        row 1: first inbound  departure (destination + minutes)
        row 2: first outbound departure
        row 3: second outbound (or a second inbound) departure
    """
    cols, _rows = matrix.capacity()
    right_x = matrix.width - 1
    minutes_chars = 3
    dest_chars = cols - minutes_chars - 1  # leave a gap before minutes

    # Row 0: header
    matrix.draw_text(0, 0, _abbreviate(station_name, cols - len(route_label) - 1), WHITE)
    matrix.draw_text_right(right_x, 0, route_label, line_color)

    inbound = sorted(
        [d for d in departures if d.direction == "Inbound"], key=lambda d: d.arrival_time
    )
    outbound = sorted(
        [d for d in departures if d.direction == "Outbound"], key=lambda d: d.arrival_time
    )

    # Pick up to 3 rows: 1 inbound, then outbound(s).
    picks: List[Departure] = []
    if inbound:
        picks.append(inbound[0])
    picks.extend(outbound[:2])
    picks = picks[:3]

    for i, dep in enumerate(picks):
        y = (i + 1) * CELL_HEIGHT
        tag = "I" if dep.direction == "Inbound" else "O"
        dest = _abbreviate(dep.destination, dest_chars - 2)
        matrix.draw_text(0, y, tag, line_color)
        matrix.draw_text(2 * CELL_WIDTH, y, dest, WHITE)
        matrix.draw_text_right(right_x, y, str(dep.minutes), AMBER)
