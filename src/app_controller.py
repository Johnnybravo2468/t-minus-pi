"""Application controller / state machine (Phase 4).

This is the small piece of glue that connects input to state:

    InputController --(abstract event)--> AppController --> StationManager

It owns the *button mapping* (which event does what). Keeping that mapping here
means:
- the input layer stays a dumb transport (it only forwards event names), and
- the StationManager stays a pure state holder (it exposes primitive actions).

The mapping can be customized later (e.g. from config) without touching either
of those layers.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from src.input_controller import (
    BUS_MODE,
    BUTTON_3,
    InputController,
    NEXT_STATION,
    PREVIOUS_STATION,
    TOGGLE,
)
from src.station_manager import StationManager

# Called after an event is handled: (event, station_manager) -> None.
ChangeCallback = Callable[[str, StationManager], None]


class AppController:
    """Routes abstract input events to StationManager operations."""

    def __init__(
        self,
        station_manager: StationManager,
        on_change: Optional[ChangeCallback] = None,
    ):
        self.stations = station_manager
        self._on_change = on_change
        # The configurable button mapping. Edit here (or override later) to
        # change what each physical button does.
        self._actions: Dict[str, Callable[[], object]] = {
            NEXT_STATION: self.stations.next_station,
            PREVIOUS_STATION: self.stations.previous_station,
            # The dedicated toggle button cycles through lines in the current
            # service (subway lines, or bus routes when those are on screen).
            TOGGLE: self.stations.next_line,
            # BUTTON_3 is a placeholder "confirm / select current" for now.
            BUTTON_3: self.stations.current_station,
            BUS_MODE: self.stations.switch_service,
        }

    def handle_event(self, event: str) -> None:
        """Apply one abstract event. Unknown events are ignored, not fatal."""
        action = self._actions.get(event)
        if action is None:
            return
        action()
        if self._on_change is not None:
            self._on_change(event, self.stations)

    def connect(self, input_controller: InputController) -> None:
        """Subscribe this controller to an input source's events."""
        input_controller.subscribe(self.handle_event)
