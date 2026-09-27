"""Tests for the LED display app's board build and interactive key mapping."""

from datetime import datetime, timedelta, timezone

from src.input_controller import BUTTON_3, NEXT_STATION, PREVIOUS_STATION, TOGGLE
from src.led_display_app import KEY_TO_EVENT, build_board
from src.rpi_led_display import RaspberryPiLEDDisplay
from src.transit_model import Departure
from tests.test_rpi_led_display import FakeOptions, FakeMatrix


def _departures():
    now = datetime.now(timezone.utc)
    return [
        Departure("Fenway", "Green Line", "Green Line (D)", "Inbound",
                  "Union Square", now + timedelta(minutes=3), branch="D"),
        Departure("Fenway", "Green Line", "Green Line (D)", "Outbound",
                  "Riverside", now + timedelta(minutes=7), branch="D"),
    ]


def test_key_map_covers_all_buttons():
    assert KEY_TO_EVENT == {
        "n": NEXT_STATION,
        "p": PREVIOUS_STATION,
        "t": TOGGLE,
        "3": BUTTON_3,
    }


def test_build_board_matches_display_size_and_draws():
    display = RaspberryPiLEDDisplay(backend=(FakeMatrix, FakeOptions))
    board = build_board(display, "Fenway", _departures())
    assert board.width == display.width  # 128
    assert board.height == display.height  # 64
    # Something was drawn (header pixels lit).
    assert any(board.get_pixel(x, y) for x in range(board.width) for y in range(7))
