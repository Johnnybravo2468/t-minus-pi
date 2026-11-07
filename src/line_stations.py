"""Build the full set of stations-of-interest from the live MBTA API.

Instead of hand-listing hundreds of stops in config, this discovers every route
(and every stop on each route) from the API and turns them into the same
``RouteConfig`` objects the StationManager already uses. The result is grouped by
line, so the toggle button cycles lines and next/previous move within a line.

    build_all_line_stations(client) -> [RouteConfig, RouteConfig, ...]
"""

from __future__ import annotations

from typing import List

from src.config import RouteConfig
from src.mbta_client import MBTAClient
from src.station_manager import _line_family

# MBTA route_type values: 0 = light rail (Green/Mattapan), 1 = heavy rail
# (Red/Orange/Blue), 2 = commuter rail.
SUBWAY_TYPES = "0,1"
SUBWAY_AND_COMMUTER_TYPES = "0,1,2"


async def build_all_line_stations(
    client: MBTAClient, include_commuter: bool = False
) -> List[RouteConfig]:
    """Discover all routes and their stops and build grouped station configs.

    Stops are de-duplicated within a line, but kept across different lines (so a
    transfer stop like Downtown Crossing appears under both Red and Orange).

    Each Green branch (B, C, D, E) is its own line, so the toggle cycles them the
    same way it cycles Red, Orange, and Blue. A trunk stop is stored once on
    every branch that serves it. Those copies share one ``route_id`` listing
    every serving branch (``Green-B,Green-D``), so the board merges all of their
    inbound and outbound trains. The station id keeps the branch being cycled
    (``Green-B:place-pktrm``).
    """
    types = SUBWAY_AND_COMMUTER_TYPES if include_commuter else SUBWAY_TYPES
    routes = await client.fetch_route_ids(types)

    stations: List[RouteConfig] = []
    seen: set = set()  # (line_family, stop_id) for non-green lines

    # Gather every Green branch before emitting stations, so a trunk stop knows
    # the full set of branches even when a later route is the one that adds it.
    green_routes: List[tuple] = []
    green_branches_by_stop: dict = {}

    for route_id, long_name in routes:
        route_type = "commuter_rail" if route_id.startswith("CR-") else "subway"
        stops = await client.fetch_route_stops(route_id)

        if route_id.startswith("Green-"):
            ordered_stops: List[dict] = []
            seen_on_branch: set = set()
            for stop in stops:
                stop_id = stop["id"]
                if stop_id in seen_on_branch:
                    continue
                seen_on_branch.add(stop_id)
                ordered_stops.append(stop)
                branches = green_branches_by_stop.setdefault(stop_id, [])
                if route_id not in branches:
                    branches.append(route_id)
            green_routes.append((route_id, long_name, ordered_stops))
            continue

        family = _family_for_route(route_id)
        for stop in stops:
            key = (family, stop["id"])
            if key in seen:
                continue
            seen.add(key)
            stations.append(
                RouteConfig(
                    id=f"{route_id}:{stop['id']}",
                    type=route_type,
                    route_id=route_id,
                    stop_id=stop["id"],
                    name=f"{stop['name']} - {long_name}",
                )
            )

    for route_id, long_name, ordered_stops in green_routes:
        for stop in ordered_stops:
            branches = green_branches_by_stop[stop["id"]]
            fetch_route = ",".join(branches) if len(branches) > 1 else route_id
            stations.append(
                RouteConfig(
                    id=f"{route_id}:{stop['id']}",
                    type="subway",
                    route_id=fetch_route,
                    stop_id=stop["id"],
                    name=f"{stop['name']} - {long_name}",
                )
            )
    return stations


def _family_for_route(route_id: str) -> str:
    return _line_family(
        RouteConfig(id="_", type="subway", route_id=route_id, stop_id="_", name="_")
    )
