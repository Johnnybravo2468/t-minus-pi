"""Adapter: MBTA client output -> normalized :class:`Departure` objects.

This is the only place that understands the shape of the dictionaries returned
by :meth:`src.mbta_client.MBTAClient.get_route_departures`. It converts that
already-parsed data into the hardware-agnostic model in ``transit_model.py``.

Keeping this bridge separate means:
- ``mbta_client.py`` stays focused on talking to the MBTA API.
- ``transit_model.py`` stays a pure data model.
- Display/input layers only ever see :class:`Departure` objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from src.config import RouteConfig
from src.mbta_client import MBTAClient
from src.transit_model import DIRECTION_LABELS, Departure, route_display


def _line_and_branch(route_id: Optional[str]) -> tuple[str, Optional[str]]:
    """Derive a human line name and optional branch from an MBTA route id.

    Examples:
        ``Green-D`` -> ("Green Line", "D")
        ``Red``     -> ("Red Line", None)
        ``39``      -> ("39", None)  # bus routes have no branch
    """
    if not route_id:
        return "", None
    if route_id.startswith("Green"):
        # A combined route like "Green-B,Green-C,Green-D,Green-E" (trunk stop
        # serving all branches) has no single branch.
        if "," in route_id:
            return "Green Line", None
        branch = route_id.split("-", 1)[1] if "-" in route_id else None
        return "Green Line", branch
    if route_id in {"Red", "Orange", "Blue"}:
        return f"{route_id} Line", None
    return route_id, None


def normalize_departures(card: dict, station_name: str) -> List[Departure]:
    """Convert one route "card" dict into a flat list of :class:`Departure`.

    ``card`` is the structure returned by ``MBTAClient.get_route_departures``.
    The precomputed ``minutes``/``countdown`` fields in the card are ignored on
    purpose: the normalized model recomputes minutes from the arrival time so it
    never goes stale.
    """
    line, branch = _line_and_branch(card.get("route_id"))
    display = route_display(line, branch)

    departures: List[Departure] = []
    for direction in card.get("directions", []):
        direction_id = direction.get("direction_id")
        direction_label = DIRECTION_LABELS.get(
            direction_id, direction.get("name", f"Direction {direction_id}")
        )
        for entry in direction.get("departures", []):
            iso_time = entry.get("arrival_time_iso") or entry.get("time_iso")
            if not iso_time:
                continue
            arrival_time = datetime.fromisoformat(iso_time)
            departures.append(
                Departure(
                    station_name=station_name,
                    line=line,
                    route_display=display,
                    direction=direction_label,
                    destination=entry.get("headsign") or "",
                    arrival_time=arrival_time,
                    branch=branch,
                    status=entry.get("status"),
                )
            )
    return departures


async def fetch_station_departures(
    client: MBTAClient,
    route_config: RouteConfig,
    station_name: str,
    max_per_direction: int = 3,
) -> List[Departure]:
    """Fetch live data via the existing client and return normalized departures."""
    card = await client.get_route_departures(
        route_config, max_per_direction=max_per_direction, include_alerts=False
    )
    return normalize_departures(card, station_name)
