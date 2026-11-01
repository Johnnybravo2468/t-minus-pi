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

    # Park Street appears once under Red and once under Green (across lines),
    # but only once within Green even though both Green-B and Green-D serve it.
    park = [s for s in stations if s.stop_id == "place-pktrm"]
    families = sorted({s.route_id.split("-")[0] for s in park})
    assert families == ["Green", "Red"]
    green_park = [s for s in park if s.route_id.startswith("Green")]
    assert len(green_park) == 1


def test_green_trunk_stop_combines_all_branches():
    stations = _build()
    # Park Street is served by Green-B and Green-D in the fixture; the combined
    # Green station should list both branches so predictions include each.
    green_park = next(
        s for s in stations if s.stop_id == "place-pktrm" and s.route_id.startswith("Green")
    )
    assert green_park.route_id == "Green-B,Green-D"
    assert green_park.name == "Park Street - Green Line"


def test_built_stations_group_into_lines():
    stations = _build()
    m = StationManager(stations)
    # Red first, then Green family.
    assert m.current_line() == "RED"
    m.next_line()
    assert m.current_line() == "GREEN"
    # Within green there are Park Street, Boylston, Fenway (deduped).
    green_names = {s.stop_id for s in stations if s.route_id.startswith("Green")}
    assert green_names == {"place-pktrm", "place-boyls", "place-fenwy"}


def test_types_filter_switches_with_commuter_flag():
    routes = [("Red", "Red Line")]
    stops = {"Red": [{"id": "place-alfcl", "name": "Alewife"}]}
    client = FakeClient(routes, stops)
    asyncio.run(build_all_line_stations(client, include_commuter=True))
    assert client.types == "0,1,2"
    asyncio.run(build_all_line_stations(client, include_commuter=False))
    assert client.types == "0,1"
