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

    Stops are de-duplicated *within a line* (so a Green-Line trunk stop served by
    several branches appears once per line), but kept across different lines (so a
    transfer stop like Downtown Crossing appears under both Red and Orange).
    """
    types = SUBWAY_AND_COMMUTER_TYPES if include_commuter else SUBWAY_TYPES
    routes = await client.fetch_route_ids(types)

    stations: List[RouteConfig] = []
    seen: set = set()  # (line_family, stop_id) for non-green lines

    # Green branches (B/C/D/E) are combined so a trunk stop shows all branches'
    # trains at once. Collect them separately, preserving first-seen stop order.
    green_branches_by_stop: dict = {}
    green_name_by_stop: dict = {}
    green_stop_order: List[str] = []

    for route_id, long_name in routes:
        route_type = "commuter_rail" if route_id.startswith("CR-") else "subway"
        stops = await client.fetch_route_stops(route_id)

        if route_id.startswith("Green-"):
            for stop in stops:
                stop_id = stop["id"]
                if stop_id not in green_branches_by_stop:
                    green_branches_by_stop[stop_id] = []
                    green_name_by_stop[stop_id] = stop["name"]
                    green_stop_order.append(stop_id)
                green_branches_by_stop[stop_id].append(route_id)
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

    # One combined Green-Line station per stop (route_id lists all serving
    # branches, e.g. "Green-B,Green-D"), so predictions include every branch.
    for stop_id in green_stop_order:
        branches = ",".join(green_branches_by_stop[stop_id])
        stations.append(
            RouteConfig(
                id=f"Green:{stop_id}",
                type="subway",
                route_id=branches,
                stop_id=stop_id,
                name=f"{green_name_by_stop[stop_id]} - Green Line",
            )
        )
    return stations


def _family_for_route(route_id: str) -> str:
    return _line_family(
        RouteConfig(id="_", type="subway", route_id=route_id, stop_id="_", name="_")
    )
