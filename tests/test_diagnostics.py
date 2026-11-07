"""Tests for LED board fault codes."""

from datetime import datetime, timedelta, timezone

from src.diagnostics import (
    API_DOWN,
    API_KEY,
    NO_DNS,
    NO_LINK,
    RATE_LIMIT,
    classify_fetch_error,
    has_default_route,
    panel_status,
)
from src.led_matrix import CELL_HEIGHT, PixelMatrix, render_station_board
from src.transit_model import Departure


def test_classify_fetch_error_names_the_failure():
    assert classify_fetch_error(None) == ""
    assert classify_fetch_error("") == ""
    assert classify_fetch_error("[Errno -3] Temporary failure in name resolution") == NO_DNS
    assert classify_fetch_error("[Errno -2] Name or service not known") == NO_DNS
    assert classify_fetch_error("Client error '429 Too Many Requests' for url") == RATE_LIMIT
    assert classify_fetch_error("Client error '403 Forbidden' for url") == API_KEY
    assert classify_fetch_error("timed out") == API_DOWN
    assert classify_fetch_error("All connection attempts failed") == API_DOWN


def test_missing_default_route_wins_over_the_fetch_error():
    assert panel_status("Temporary failure in name resolution", link_up=False) == NO_LINK
    assert panel_status("Temporary failure in name resolution", link_up=True) == NO_DNS
    assert panel_status(None, link_up=True) == ""
    assert panel_status(None, link_up=None) == ""


def test_has_default_route_reads_proc_net_route():
    table = (
        "Iface\tDestination\tGateway\tFlags\n"
        "eth0\t00000000\t0101A8C0\t0003\t0\t0\t0\n"
        "wlan0\t0000A8C0\t00000000\t0001\t0\t0\t0\n"
    )
    assert has_default_route(table) is True
    assert has_default_route("Iface\tDestination\tGateway\neth0\t0000A8C0\t00000000\n") is False


def test_tall_board_draws_status_on_the_spare_row():
    now = datetime.now(timezone.utc)
    departures = [
        Departure(
            "Park Street",
            "Green Line",
            "Green Line",
            "Inbound",
            "Boston College",
            now + timedelta(minutes=4),
        )
    ]
    shown = PixelMatrix(128, 64)
    render_station_board(shown, "Park Street", "GREEN B", departures, status="NO LINK")
    status_lit = any(
        shown.get_pixel(x, y)
        for x in range(128)
        for y in range(CELL_HEIGHT, CELL_HEIGHT + 7)
    )
    assert status_lit

    plain = PixelMatrix(128, 64)
    render_station_board(plain, "Park Street", "GREEN B", departures)
    blank = any(
        plain.get_pixel(x, y)
        for x in range(128)
        for y in range(CELL_HEIGHT, CELL_HEIGHT + 7)
    )
    assert not blank
