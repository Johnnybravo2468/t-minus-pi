"""Tests for the LED display app's board build and interactive key mapping."""

from datetime import datetime, timedelta, timezone

from src.input_controller import BUTTON_3, NEXT_STATION, PREVIOUS_STATION, TOGGLE
from src.led_display_app import KEY_TO_EVENT, _make_display, _parse_args, build_board
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


def test_parse_args_defaults_and_triple_bonnet(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog"])
    args = _parse_args()
    assert args.gpio_mapping == "adafruit-hat"
    assert args.rows == 64 and args.cols == 64
    assert args.chain == 2 and args.parallel == 1

    monkeypatch.setattr("sys.argv", ["prog", "--gpio-mapping", "regular", "--parallel", "2"])
    args = _parse_args()
    assert args.gpio_mapping == "regular"
    assert args.parallel == 2


def test_make_display_forwards_mapping(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog", "--gpio-mapping", "regular"])
    args = _parse_args()
    # Build with the fake backend so no hardware is needed.
    monkeypatch.setattr(
        "src.led_display_app.RaspberryPiLEDDisplay",
        lambda **kw: RaspberryPiLEDDisplay(backend=(FakeMatrix, FakeOptions), **kw),
    )
    _make_display(args)
    assert FakeMatrix.last_instance.options.hardware_mapping == "regular"
    # App keeps privileges by default so it can read the venv under /home.
    assert FakeMatrix.last_instance.options.drop_privileges is False


def test_drop_privileges_flag_opts_in(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog", "--drop-privileges"])
    args = _parse_args()
    monkeypatch.setattr(
        "src.led_display_app.RaspberryPiLEDDisplay",
        lambda **kw: RaspberryPiLEDDisplay(backend=(FakeMatrix, FakeOptions), **kw),
    )
    _make_display(args)
    assert FakeMatrix.last_instance.options.drop_privileges is True


def test_build_board_matches_display_size_and_draws():
    display = RaspberryPiLEDDisplay(backend=(FakeMatrix, FakeOptions))
    board = build_board(display, "Fenway", _departures())
    assert board.width == display.width  # 128
    assert board.height == display.height  # 64
    # Something was drawn (header pixels lit).
    assert any(board.get_pixel(x, y) for x in range(board.width) for y in range(7))
