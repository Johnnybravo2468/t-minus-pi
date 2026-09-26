"""Tests for the LED font and pixel-matrix simulation (feasibility tooling)."""

import string
from datetime import datetime, timedelta, timezone

from src.led_font import FONT_5x7, GLYPH_HEIGHT, GLYPH_WIDTH, glyph
from src.led_matrix import (
    CELL_HEIGHT,
    CELL_WIDTH,
    PixelMatrix,
    _abbreviate,
    render_station_board,
)
from src.transit_model import Departure


def test_font_covers_letters_and_digits():
    for ch in string.ascii_uppercase + string.digits + " ":
        assert ch in FONT_5x7, f"missing glyph for {ch!r}"


def test_every_glyph_is_correct_size():
    for ch, bitmap in FONT_5x7.items():
        assert len(bitmap) == GLYPH_HEIGHT, f"{ch!r} wrong height"
        assert all(len(row) == GLYPH_WIDTH for row in bitmap), f"{ch!r} wrong width"


def test_unknown_glyph_is_blank():
    assert glyph("~") == [[0] * GLYPH_WIDTH for _ in range(GLYPH_HEIGHT)]


def test_pixel_set_get_and_bounds():
    m = PixelMatrix(10, 5)
    m.set_pixel(2, 3, (1, 2, 3))
    assert m.get_pixel(2, 3) == (1, 2, 3)
    # Out of bounds is ignored, not an error.
    m.set_pixel(100, 100, (9, 9, 9))
    assert m.get_pixel(0, 0) is None


def test_draw_char_lights_expected_pixels():
    m = PixelMatrix(6, 8)
    color = (255, 255, 255)
    m.draw_char(0, 0, "-", color)  # '-' lights only the middle row (row 3)
    assert all(m.get_pixel(x, 3) == color for x in range(GLYPH_WIDTH))
    assert m.get_pixel(0, 0) is None


def test_draw_text_advances_cursor():
    m = PixelMatrix(96, 32)
    end = m.draw_text(0, 0, "ABC", (255, 255, 255))
    assert end == 3 * CELL_WIDTH


def test_capacity_for_32x96_panel():
    m = PixelMatrix(96, 32)
    assert (CELL_WIDTH, CELL_HEIGHT) == (6, 8)
    assert m.capacity() == (16, 4)


def test_to_ascii_dimensions():
    m = PixelMatrix(96, 32)
    lines = m.to_ascii().splitlines()
    assert len(lines) == 32
    assert all(len(line) == 96 for line in lines)


def test_abbreviate_shortens_common_words():
    assert _abbreviate("Union Square", 16) == "UNION SQ"
    assert _abbreviate("Government Center", 16) == "GOVERNMENT CTR"
    # Falls back to truncation when still too long.
    assert _abbreviate("Extremely Long Name", 6) == "EXTREM"


def test_render_station_board_lights_pixels():
    now = datetime.now(timezone.utc)
    departures = [
        Departure("Fenway", "Green Line", "Green Line (D)", "Inbound",
                  "Union Square", now + timedelta(minutes=3), branch="D"),
        Departure("Fenway", "Green Line", "Green Line (D)", "Outbound",
                  "Riverside", now + timedelta(minutes=7), branch="D"),
    ]
    m = PixelMatrix(96, 32)
    render_station_board(m, "Fenway", "GRN D", departures)
    # Something was drawn in the header row and at least one departure row.
    header_lit = any(m.get_pixel(x, y) for x in range(96) for y in range(GLYPH_HEIGHT))
    dep_lit = any(
        m.get_pixel(x, y)
        for x in range(96)
        for y in range(CELL_HEIGHT, CELL_HEIGHT + GLYPH_HEIGHT)
    )
    assert header_lit
    assert dep_lit
