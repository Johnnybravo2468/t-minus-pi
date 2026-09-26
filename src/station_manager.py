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

    def next_station(self) -> RouteConfig:
        """Advance to the next station, wrapping around to the first."""
        self._index = (self._index + 1) % self.station_count
        return self.current_station()

    def previous_station(self) -> RouteConfig:
        """Go to the previous station, wrapping around to the last."""
        self._index = (self._index - 1) % self.station_count
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
