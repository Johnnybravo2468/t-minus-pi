"""Tests for the normalized transit model and the MBTA->model adapter."""

from datetime import datetime, timedelta, timezone

from src.transit_model import Departure, route_display
from src.transit_service import _line_and_branch, normalize_departures


def _sample_card():
    """A trimmed version of MBTAClient.get_route_departures output for Green-D."""
    now = datetime.now(timezone.utc)
    return {
        "id": "fenway_green_d",
        "name": "Fenway - Green Line (D)",
        "type": "subway",
        "stop_id": "place-fenwy",
        "route_id": "Green-D",
        "directions": [
            {
                "direction_id": 1,
                "name": "Union Square (Inbound)",
                "departures": [
                    {
                        "headsign": "Union Square",
                        "arrival_time_iso": (now + timedelta(minutes=3)).isoformat(),
                        "status": None,
                        "minutes": 999,  # deliberately wrong; must be ignored
                        "countdown": "999 min",
                    }
                ],
            },
            {
                "direction_id": 0,
                "name": "Riverside (Outbound)",
                "departures": [
                    {
                        "headsign": "Riverside",
                        "arrival_time_iso": (now + timedelta(minutes=7)).isoformat(),
                        "status": "On Time",
                    }
                ],
            },
        ],
    }


def test_route_display():
    assert route_display("Green Line", "D") == "Green Line (D)"
    assert route_display("Red Line", None) == "Red Line"


def test_line_and_branch():
    assert _line_and_branch("Green-D") == ("Green Line", "D")
    assert _line_and_branch("Red") == ("Red Line", None)
    assert _line_and_branch("39") == ("39", None)
    # A combined Green trunk route has no single branch.
    assert _line_and_branch("Green-B,Green-C,Green-D,Green-E") == ("Green Line", None)


def test_normalize_departures_maps_fields_and_directions():
    card = _sample_card()
    departures = normalize_departures(card, station_name="Fenway")

    assert len(departures) == 2

    inbound = [d for d in departures if d.direction == "Inbound"]
    outbound = [d for d in departures if d.direction == "Outbound"]
    assert len(inbound) == 1
    assert len(outbound) == 1

    inbound_dep = inbound[0]
    assert inbound_dep.station_name == "Fenway"
    assert inbound_dep.line == "Green Line"
    assert inbound_dep.branch == "D"
    assert inbound_dep.route_display == "Green Line (D)"
    assert inbound_dep.destination == "Union Square"
    assert outbound[0].status == "On Time"


def test_minutes_is_derived_from_arrival_time_not_stale_field():
    card = _sample_card()
    departures = normalize_departures(card, station_name="Fenway")
    inbound_dep = [d for d in departures if d.direction == "Inbound"][0]

    # The card claimed minutes=999; the model must recompute ~3 from arrival_time.
    assert 2 <= inbound_dep.minutes <= 3


def test_minutes_never_negative_for_past_arrival():
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    dep = Departure(
        station_name="Fenway",
        line="Green Line",
        route_display="Green Line (D)",
        direction="Inbound",
        destination="Union Square",
        arrival_time=past,
        branch="D",
    )
    assert dep.minutes == 0
    assert dep.countdown_label() == "ARR"
