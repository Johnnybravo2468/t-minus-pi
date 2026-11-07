"""Tests for building the full station list from the MBTA API."""

import asyncio

from src.line_stations import build_all_line_stations
from src.station_manager import StationManager


class FakeClient:
    """Stand-in for MBTAClient returning canned routes/stops (no network)."""

    def __init__(self, routes, stops_by_route):
        self._routes = routes
        self._stops = stops_by_route

    async def fetch_route_ids(self, types):
        self.types = types
        return self._routes

    async def fetch_route_stops(self, route_id):
        return self._stops[route_id]


def _build(include_commuter=False):
    routes = [("Red", "Red Line"), ("Green-B", "Green Line B"), ("Green-D", "Green Line D")]
    stops = {
        "Red": [{"id": "place-dwnxg", "name": "Downtown Crossing"},
                {"id": "place-pktrm", "name": "Park Street"}],
        "Green-B": [{"id": "place-pktrm", "name": "Park Street"},
                    {"id": "place-boyls", "name": "Boylston"}],
        "Green-D": [{"id": "place-pktrm", "name": "Park Street"},
                    {"id": "place-fenwy", "name": "Fenway"}],
    }
    client = FakeClient(routes, stops)
    return asyncio.run(build_all_line_stations(client, include_commuter=include_commuter))


def test_dedup_within_line_but_keep_across_lines():
    stations = _build()

    # Park Street is one Red station and one station on each Green branch that
    # serves it. The branch copies are duplicates of the same physical stop.
    park = [s for s in stations if s.stop_id == "place-pktrm"]
    assert sorted(s.id for s in park) == [
        "Green-B:place-pktrm",
        "Green-D:place-pktrm",
        "Red:place-pktrm",
    ]


def test_green_trunk_stop_combines_all_branches():
    stations = _build()
    # Each branch keeps its own Park Street. Both copies list every serving
    # branch so the board merges inbound and outbound trains from all of them.
    green_park = [
        s for s in stations if s.stop_id == "place-pktrm" and s.id.startswith("Green-")
    ]
    assert [s.id for s in green_park] == ["Green-B:place-pktrm", "Green-D:place-pktrm"]
    assert {s.route_id for s in green_park} == {"Green-B,Green-D"}
    assert [s.name for s in green_park] == [
        "Park Street - Green Line B",
        "Park Street - Green Line D",
    ]


def test_branch_only_stop_keeps_its_own_route():
    stations = _build()
    fenway = next(s for s in stations if s.stop_id == "place-fenwy")
    assert fenway.id == "Green-D:place-fenwy"
    assert fenway.route_id == "Green-D"
    boylston = next(s for s in stations if s.stop_id == "place-boyls")
    assert boylston.id == "Green-B:place-boyls"
    assert boylston.route_id == "Green-B"


def test_built_stations_group_into_lines():
    stations = _build()
    m = StationManager(stations)
    # Red first, then each Green branch as its own line.
    assert m.current_line() == "RED"
    m.next_line()
    assert m.current_line() == "GREEN-B"
    assert m.current_station().id == "Green-B:place-pktrm"
    assert m.next_station().id == "Green-B:place-boyls"
    assert m.next_station().id == "Green-B:place-pktrm"  # wraps inside B
    m.next_line()
    assert m.current_line() == "GREEN-D"
    assert m.current_station().id == "Green-D:place-pktrm"
    assert m.next_station().id == "Green-D:place-fenwy"


def test_types_filter_switches_with_commuter_flag():
    routes = [("Red", "Red Line")]
    stops = {"Red": [{"id": "place-alfcl", "name": "Alewife"}]}
    client = FakeClient(routes, stops)
    asyncio.run(build_all_line_stations(client, include_commuter=True))
    assert client.types == "0,1,2"
    asyncio.run(build_all_line_stations(client, include_commuter=False))
    assert client.types == "0,1"
