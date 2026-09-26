"""Tests for the Phase 3 display encoder and drivers."""

from datetime import datetime, timedelta, timezone

from src.display_driver import ConsoleDisplay, SimulatedLEDDisplay
from src.display_encoder import (
    DEFAULT_WIDTH,
    DisplayEncoder,
    DisplayFrame,
    compact_route_label,
)
from src.transit_model import Departure


def _dep(direction: str, destination: str, minutes_ahead: int) -> Departure:
    return Departure(
        station_name="Fenway",
        line="Green Line",
        route_display="Green Line (D)",
        direction=direction,
        destination=destination,
        arrival_time=datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead),
        branch="D",
    )


def _sample_departures():
    return [
        _dep("Inbound", "Union Square", 3),
        _dep("Inbound", "Union Square", 15),
        _dep("Outbound", "Riverside", 7),
        _dep("Outbound", "Riverside", 21),
    ]


def test_frame_pads_all_rows_to_width():
    frame = DisplayFrame(width=20, rows=["short", "x" * 40])
    assert all(len(row) == 20 for row in frame.rows)
    assert frame.rows[0] == "short".ljust(20)
    assert frame.rows[1] == "x" * 20  # truncated


def test_compact_route_label():
    dep = _dep("Inbound", "Union Square", 3)
    assert compact_route_label(dep) == "GREEN D"
    red = Departure(
        station_name="s", line="Red Line", route_display="Red Line",
        direction="Inbound", destination="Alewife",
        arrival_time=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    assert compact_route_label(red) == "RED"


def test_encode_layout_structure():
    encoder = DisplayEncoder()
    frame = encoder.encode("Fenway", _sample_departures())
    text = frame.as_text()

    assert frame.width == DEFAULT_WIDTH
    assert all(len(row) == DEFAULT_WIDTH for row in frame.rows)

    # Header has station on the left and compact route on the right.
    assert frame.rows[0].startswith("FENWAY")
    assert frame.rows[0].rstrip().endswith("GREEN D")

    # Section headers present and in order (Inbound before Outbound).
    assert "INBOUND" in text
    assert "OUTBOUND" in text
    assert text.index("INBOUND") < text.index("OUTBOUND")

    # Destinations are uppercased.
    assert "UNION SQUARE" in text
    assert "RIVERSIDE" in text


def test_encode_respects_max_per_direction():
    encoder = DisplayEncoder(max_per_direction=1)
    frame = encoder.encode("Fenway", _sample_departures())
    text = frame.as_text()
    # Only one row per direction -> "Union Square" appears once.
    assert text.count("UNION SQUARE") == 1
    assert text.count("RIVERSIDE") == 1


def test_encode_handles_empty_departures():
    encoder = DisplayEncoder()
    frame = encoder.encode("Fenway", [], route_label="GREEN D")
    text = frame.as_text()
    assert "INBOUND" in text
    assert "OUTBOUND" in text
    assert "(NO SERVICE)" in text.upper()


def test_departure_row_shows_minutes_right_aligned():
    encoder = DisplayEncoder()
    dep = _dep("Inbound", "Union Square", 6)
    row = encoder._departure_row(dep)
    assert row.startswith("UNION SQUARE")
    assert row.rstrip().endswith(str(dep.minutes))


def test_simulated_led_display_draws_border(capsys):
    frame = DisplayEncoder().encode("Fenway", _sample_departures())
    SimulatedLEDDisplay().render(frame)
    out = capsys.readouterr().out
    assert out.startswith("+")
    assert "| FENWAY" in out
    # Border width matches frame width + padding.
    assert ("-" * (frame.width + 2)) in out


def test_console_display_plain(capsys):
    frame = DisplayEncoder().encode("Fenway", _sample_departures())
    ConsoleDisplay().render(frame)
    out = capsys.readouterr().out
    assert "FENWAY" in out
    assert "+" not in out.splitlines()[0]  # no border
