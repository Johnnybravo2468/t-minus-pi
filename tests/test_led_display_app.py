"""Tests for the LED display app's board build and interactive key mapping."""

import asyncio
from datetime import datetime, timedelta, timezone

import src.led_display_app as app
from src.config import RouteConfig
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


def test_departure_cache_prevents_repeated_fetches(monkeypatch):
    app._DEPARTURE_CACHE.clear()
    calls = {"n": 0}

    async def fake_fetch(client, station, station_name, max_per_direction=3):
        calls["n"] += 1
        return _departures()

    monkeypatch.setattr(app, "fetch_station_departures", fake_fetch)
    station = RouteConfig(id="s1", type="subway", route_id="Red",
                          stop_id="place-dwnxg", name="Downtown Crossing")

    async def run():
        a = await app._get_departures(None, station, "Downtown Crossing")
        b = await app._get_departures(None, station, "Downtown Crossing")
        return a, b

    a, b = asyncio.run(run())
    assert calls["n"] == 1          # second call served from cache
    assert a is b


def test_cache_keeps_last_good_on_empty_fetch(monkeypatch):
    app._DEPARTURE_CACHE.clear()
    station = RouteConfig(id="s2", type="subway", route_id="Red",
                          stop_id="place-dwnxg", name="Downtown Crossing")
    good = _departures()
    seq = [good, []]  # first succeeds, then a rate-limited empty result

    async def fake_fetch(client, station, station_name, max_per_direction=3):
        return seq.pop(0)

    monkeypatch.setattr(app, "fetch_station_departures", fake_fetch)
    # Force the cache to expire between the two fetches.
    monkeypatch.setattr(app, "CACHE_TTL_SECONDS", 0.0)

    async def run():
        first = await app._get_departures(None, station, "x")
        second = await app._get_departures(None, station, "x")
        return first, second

    first, second = asyncio.run(run())
    assert first == good
    assert second == good  # empty fetch fell back to last good board
