"""Tests for the LED display app's board build and interactive key mapping."""

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import src.led_display_app as app
from src.app_controller import AppController
from src.config import RouteConfig
from src.input_controller import (
    BUS_MODE,
    BUTTON_3,
    NEXT_STATION,
    PREVIOUS_STATION,
    SimulatedInputController,
    TOGGLE,
)
from src.station_manager import StationManager
from src.led_display_app import KEY_TO_EVENT, _make_display, _parse_args, build_board
from src.led_matrix import GREEN, WHITE, PixelMatrix, render_station_board
from src.rpi_led_display import RaspberryPiLEDDisplay
from src.transit_model import Departure
from src.transit_service import StationFetch
from tests.test_rpi_led_display import FakeOptions, FakeMatrix


def _departures():
    now = datetime.now(timezone.utc)
    return [
        Departure("Fenway", "Green Line", "Green Line (D)", "Inbound",
                  "Union Square", now + timedelta(minutes=3), branch="D"),
        Departure("Fenway", "Green Line", "Green Line (D)", "Outbound",
                  "Riverside", now + timedelta(minutes=7), branch="D"),
    ]


def test_header_names_mark_branch_only_green_stops():
    fenway = RouteConfig(
        id="Green-D:place-fenwy",
        type="subway",
        route_id="Green-D",
        stop_id="place-fenwy",
        name="Fenway - Green Line D",
    )
    park = RouteConfig(
        id="Green-D:place-pktrm",
        type="subway",
        route_id="Green-B,Green-C,Green-D,Green-E",
        stop_id="place-pktrm",
        name="Park Street - Green Line D",
    )
    red = RouteConfig(
        id="Red:place-dwnxg",
        type="subway",
        route_id="Red",
        stop_id="place-dwnxg",
        name="Downtown Crossing - Red Line",
    )
    assert app.station_header_name(fenway) == "Fenway (D)"
    assert app.station_header_name(park) == "Park Street (D)"
    park_b = park.model_copy(update={"id": "Green-B:place-pktrm"})
    assert app.station_header_name(park_b) == "Park Street (B)"
    assert app.station_header_name(red) == "Downtown Crossing"
    park_dr = RouteConfig(
        id="47:1807", type="bus", route_id="47", stop_id="1807", name="Park Dr at Fenway",
    )
    brookline = RouteConfig(
        id="47:1806", type="bus", route_id="47", stop_id="1806", name="Brookline Ave at Fenway",
    )
    copley = RouteConfig(
        id="9:175", type="bus", route_id="9", stop_id="175", name="Copley",
    )
    assert app.station_header_name(park_dr) == "Park Dr at Fenway (47)"
    assert app.station_header_name(brookline) == "Brookline Ave at Fenway (47)"
    assert app.station_header_name(copley) == "Copley (9)"


def test_format_clock_uses_the_given_zone():
    eastern = datetime(2026, 11, 7, 13, 5, tzinfo=ZoneInfo("America/New_York"))
    assert app.format_clock(eastern) == "1:05 PM"


def test_clock_is_white_and_replaces_the_line_label():
    now = datetime.now(timezone.utc)
    departures = [
        Departure(
            "Fenway", "Green Line", "Green Line (D)", "Inbound",
            "Union Square", now + timedelta(minutes=3), branch="D",
        ),
    ]
    matrix = PixelMatrix(128, 64)
    render_station_board(
        matrix, "Fenway (D)", "", departures, line_color=GREEN, clock="1:05 PM",
    )
    header = [
        matrix.get_pixel(x, y)
        for y in range(7)
        for x in range(matrix.width)
        if matrix.get_pixel(x, y) is not None
    ]
    assert GREEN in header
    assert WHITE in header


def test_bus_stop_name_stays_white():
    display = RaspberryPiLEDDisplay(backend=(FakeMatrix, FakeOptions))
    now = datetime.now(timezone.utc)
    # A rail-colored departure must not recolor a bus stop name.
    departures = [
        Departure(
            "Copley", "Green Line", "Green Line (D)", "Outbound",
            "Riverside", now + timedelta(minutes=4), branch="D",
        ),
    ]
    board = build_board(display, "Copley (9)", departures, line_hint="BUS-9")
    header = {
        board.get_pixel(x, y)
        for y in range(7)
        for x in range(board.width)
        if board.get_pixel(x, y) is not None
    }
    assert header == {WHITE}


def test_route_number_survives_a_narrow_header():
    from src.led_matrix import _abbreviate

    assert _abbreviate("Park Dr at Fenway (47)", 13) == "PARK DR (47)"
    assert _abbreviate("Brookline Ave at Fenway (47)", 13) == "BROOKLIN (47)"
    assert _abbreviate("Copley (9)", 13) == "COPLEY (9)"
    assert _abbreviate("Fenway (D)", 13) == "FENWAY (D)"


def test_key_map_covers_all_buttons():
    assert KEY_TO_EVENT == {
        "n": NEXT_STATION,
        "p": PREVIOUS_STATION,
        "t": TOGGLE,
        "b": BUS_MODE,
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


def test_failed_refresh_names_the_fault_and_keeps_the_board(monkeypatch):
    app._DEPARTURE_CACHE.clear()
    app._LAST_STATUS = ""
    app._PRINTED_STATUS = None
    station = RouteConfig(id="s3", type="subway", route_id="Red",
                          stop_id="place-dwnxg", name="Downtown Crossing")
    good = _departures()
    calls = {"n": 0}

    async def fake_fetch(client, station, station_name, max_per_direction=3):
        calls["n"] += 1
        if calls["n"] == 1:
            return StationFetch(departures=good)
        return StationFetch(
            departures=[],
            error="[Errno -3] Temporary failure in name resolution",
        )

    monkeypatch.setattr(app, "fetch_station_departures", fake_fetch)
    monkeypatch.setattr(app, "has_default_route", lambda: True)
    monkeypatch.setattr(app, "CACHE_TTL_SECONDS", 0.0)

    async def run():
        first = await app._get_departures(None, station, "x")
        second = await app._get_departures(None, station, "x")
        return first, second

    first, second = asyncio.run(run())
    assert first == good
    assert second == good
    assert app._LAST_STATUS == "NO DNS"


def test_interactive_refresh_keeps_the_current_station():
    stations = [
        RouteConfig(id="a", type="subway", route_id="Red", stop_id="s1", name="Alpha"),
        RouteConfig(id="b", type="subway", route_id="Red", stop_id="s2", name="Beta"),
    ]
    manager = StationManager(stations)
    inputs = SimulatedInputController()
    AppController(manager).connect(inputs)
    script = [None, "n", None, "q"]

    async def read_line(interval):
        return script.pop(0)

    rendered = []

    async def render():
        rendered.append(manager.current_station().id)

    asyncio.run(app._interactive_loop(manager, inputs, 15, read_line, render))
    # Timeout refreshes Alpha. "n" moves to Beta. The next timeout stays on Beta.
    assert rendered == ["a", "b", "b"]
    assert manager.current_station().id == "b"
