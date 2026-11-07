"""Station selection / display state (Phase 2).

The :class:`StationManager` remembers your configured "stations of interest" and
which one is currently selected. It is deliberately small and hardware-agnostic:

- It does NOT call the MBTA API or parse JSON (that is ``mbta_client`` +
  ``transit_service``).
- It does NOT know about buttons, GPIO, or wireless protocols (that is the
  future ``InputController``).
- It does NOT render anything (that is the future display encoder).

It only answers "which station is selected right now?" and lets you change that
selection. It stores station *definitions* (static config), never live
departures, so it can never hold stale data.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Union

from src.config import AppConfig, DirectionConfig, RouteConfig, load_config


class DisplayMode(Enum):
    """Coarse display state that the toggle button flips between.

    What each mode *means* on screen is decided later by the display layer; the
    manager only tracks which one is active.
    """

    NORMAL = "Normal Display Mode"
    STATION_SELECT = "Station Selection Mode"


def _green_branch_family(station: RouteConfig) -> Optional[str]:
    """Return ``GREEN-B`` (or C/D/E) when this station belongs to one branch.

    Trunk stops store every serving branch in ``route_id`` (``Green-B,Green-D``)
    and keep the branch being cycled in the station id (``Green-B:place-pktrm``).
    A single-branch station can carry it in ``route_id`` alone (``Green-D``).
    """
    head = (station.id or "").split(":", 1)[0]
    route_id = station.route_id or ""
    candidates = [head]
    if "," not in route_id:
        candidates.append(route_id)
    for value in candidates:
        text = value.upper()
        suffix = text.split("-", 1)[1] if text.startswith("GREEN-") else ""
        if len(suffix) == 1 and suffix.isalpha():
            return text
    if route_id.upper().startswith("GREEN"):
        return "GREEN"
    return None


def _line_family(station: RouteConfig) -> str:
    """Group a station into the line used for cycling.

    Each Green branch is its own line (``GREEN-B``, ``GREEN-C``, ``GREEN-D``,
    ``GREEN-E``), same as Red, Orange, and Blue. Each bus route is its own
    line (``BUS-47``). Other routes stay one family each: ``RED``, ``ORANGE``,
    ``BLUE``, ``COMMUTER``.
    """
    green = _green_branch_family(station)
    if green:
        return green
    route_id = (station.route_id or "").upper()
    for family in ("RED", "ORANGE", "BLUE"):
        if route_id.startswith(family):
            return family
    if (station.type or "").lower() == "bus":
        route = (station.route_id or "").split(",")[0].strip()
        return f"BUS-{route}" if route else "BUS"
    if route_id.startswith("CR-"):
        return "COMMUTER"
    return route_id or (station.type or "").upper()


def _service_mode(station: RouteConfig) -> str:
    """``bus`` for a bus route, ``rail`` for subway and commuter stops."""
    return "bus" if _line_family(station).startswith("BUS-") else "rail"


def _green_d_station(station_id: str, name: str, stop_id: str) -> RouteConfig:
    """Helper to build a Green Line (D) station definition."""
    return RouteConfig(
        id=station_id,
        type="subway",
        route_id="Green-D",
        stop_id=stop_id,
        name=name,
        directions=[
            DirectionConfig(direction_id=1, headsign="Union Square (Inbound)"),
            DirectionConfig(direction_id=0, headsign="Riverside (Outbound)"),
        ],
    )


# Built-in fallback used when no `stations:` are configured in config.yaml, so
# the Phase 2 demo runs out of the box.
DEFAULT_STATIONS: List[RouteConfig] = [
    _green_d_station("fenway_green_d", "Fenway - Green Line (D)", "place-fenwy"),
    _green_d_station("kenmore_green_d", "Kenmore - Green Line (D)", "place-kencl"),
    _green_d_station("longwood_green_d", "Longwood - Green Line (D)", "place-longw"),
]


class StationManager:
    """Holds the list of stations of interest and the current selection."""

    def __init__(
        self,
        stations: List[RouteConfig],
        mode: DisplayMode = DisplayMode.NORMAL,
    ):
        if not stations:
            raise ValueError("StationManager requires at least one station")
        self._stations: List[RouteConfig] = list(stations)
        self._index: int = 0
        self._mode: DisplayMode = mode
        # Last selection on the other service, so the bus button can return
        # to the subway stop that was on screen.
        self._mode_index: dict = {"rail": None, "bus": None}

    # --- selection state ---------------------------------------------------

    def current_station(self) -> RouteConfig:
        """The station that is currently selected."""
        return self._stations[self._index]

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def station_count(self) -> int:
        return len(self._stations)

    def _indices_for_current_line(self) -> List[int]:
        family = self.current_line()
        return [i for i, s in enumerate(self._stations) if _line_family(s) == family]

    def next_station(self) -> RouteConfig:
        """Advance to the next station *within the current line* (wraps)."""
        indices = self._indices_for_current_line()
        position = indices.index(self._index)
        self._index = indices[(position + 1) % len(indices)]
        return self.current_station()

    def previous_station(self) -> RouteConfig:
        """Go to the previous station *within the current line* (wraps)."""
        indices = self._indices_for_current_line()
        position = indices.index(self._index)
        self._index = indices[(position - 1) % len(indices)]
        return self.current_station()

    # --- line cycling ------------------------------------------------------

    def current_line(self) -> str:
        """The line of the currently selected station (e.g. 'GREEN-D' or 'RED')."""
        return _line_family(self.current_station())

    def service_mode(self) -> str:
        """``rail`` or ``bus``, whichever list is on screen."""
        return _service_mode(self.current_station())

    def _line_order(self, mode: Optional[str] = None) -> List[str]:
        """Distinct line families in configured order.

        ``mode`` keeps subway cycling inside the rail list and bus cycling
        inside the bus list.
        """
        order: List[str] = []
        for station in self._stations:
            if mode is not None and _service_mode(station) != mode:
                continue
            family = _line_family(station)
            if family not in order:
                order.append(family)
        return order

    def _indices_for_mode(self, mode: str) -> List[int]:
        return [i for i, station in enumerate(self._stations) if _service_mode(station) == mode]

    def next_line(self) -> RouteConfig:
        """Jump to the first station of the next line family (wraps around).

        If only one line is configured, this is a no-op. This is what the
        dedicated toggle button drives. Subway lines and bus routes stay in
        separate cycles; the bus button moves between those cycles.
        """
        families = self._line_order(self.service_mode())
        if len(families) <= 1:
            return self.current_station()
        current = self.current_line()
        next_family = families[(families.index(current) + 1) % len(families)]
        for i, station in enumerate(self._stations):
            if _line_family(station) == next_family:
                self._index = i
                break
        return self.current_station()

    def switch_service(self) -> RouteConfig:
        """Swap between the subway lines and the bus routes.

        Each side remembers the stop that was selected, so a second press
        returns to it. With no bus routes loaded, the selection stays put.
        """
        current = self.service_mode()
        self._mode_index[current] = self._index
        target = "rail" if current == "bus" else "bus"
        indices = self._indices_for_mode(target)
        if not indices:
            return self.current_station()
        saved = self._mode_index.get(target)
        self._index = saved if saved in indices else indices[0]
        return self.current_station()

    def select_station(self, station: Union[int, str]) -> RouteConfig:
        """Select a station directly by list index or by its configured ``id``.

        An integer index wraps around (so it is always valid); a string must
        match a station id exactly or a ``ValueError`` is raised.
        """
        if isinstance(station, bool):  # guard: bool is a subclass of int
            raise TypeError("station must be an int index or str id, not bool")
        if isinstance(station, int):
            self._index = station % self.station_count
            return self.current_station()
        for i, configured in enumerate(self._stations):
            if configured.id == station:
                self._index = i
                return self.current_station()
        raise ValueError(f"No station with id {station!r}")

    def select_stop(self, stop_id: str, line: Optional[str] = None) -> bool:
        """Select the first station with this MBTA stop id.

        ``line`` limits the match to one family, such as ``GREEN-D``, so a
        trunk stop that exists on several branches does not pick the wrong copy.
        Returns False when nothing matches and leaves the current selection.
        """
        for i, station in enumerate(self._stations):
            if station.stop_id != stop_id:
                continue
            if line is not None and _line_family(station) != line:
                continue
            self._index = i
            return True
        return False

    # --- display mode ------------------------------------------------------

    @property
    def mode(self) -> DisplayMode:
        return self._mode

    def toggle_mode(self) -> DisplayMode:
        """Flip between the two display modes and return the new mode."""
        self._mode = (
            DisplayMode.STATION_SELECT
            if self._mode is DisplayMode.NORMAL
            else DisplayMode.NORMAL
        )
        return self._mode


def station_manager_from_config(config: Optional[AppConfig] = None) -> StationManager:
    """Build a StationManager from configuration.

    Uses ``config.stations`` if any are configured, otherwise falls back to
    :data:`DEFAULT_STATIONS` so the demo works without editing ``config.yaml``.
    """
    if config is None:
        config = load_config()
    stations = config.stations or DEFAULT_STATIONS
    return StationManager(stations)
