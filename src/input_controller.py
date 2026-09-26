"""Input controller abstraction (Phase 4).

The rest of the application should only ever see *abstract events* such as
``NEXT_STATION`` or ``TOGGLE`` — never GPIO pins, Wi-Fi, Bluetooth, MQTT, serial,
or any specific wireless module. This module defines that seam.

    physical buttons / wireless I/O  ->  InputController  ->  abstract events

- :class:`InputController` is the interface. Subscribers register a handler and
  receive event strings.
- :class:`SimulatedInputController` lets tests or the keyboard inject events via
  :meth:`~SimulatedInputController.emit`, so the whole app can be driven on
  Windows with no hardware.

A future ``WirelessInputController`` (Phase 5) would subclass ``InputController``
and call ``self._dispatch(event)`` whenever the physical module reports a button
press. Nothing else in the app would change, because everyone depends on the
abstract events, not the transport.
"""

from __future__ import annotations

from abc import ABC
from typing import Callable, List

# Canonical abstract events. The mapping from a button to one of these lives in
# the application layer (see app_controller.py), not here, so it can be changed
# without touching input transport or transit logic.
NEXT_STATION = "NEXT_STATION"
PREVIOUS_STATION = "PREVIOUS_STATION"
TOGGLE = "TOGGLE"
BUTTON_3 = "BUTTON_3"

KNOWN_EVENTS = frozenset({NEXT_STATION, PREVIOUS_STATION, TOGGLE, BUTTON_3})

EventHandler = Callable[[str], None]


class InputController(ABC):
    """Base class for anything that produces abstract input events."""

    def __init__(self) -> None:
        self._handlers: List[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        """Register a callback invoked with the event string on each press."""
        self._handlers.append(handler)

    def _dispatch(self, event: str) -> None:
        """Send an event to every subscriber. Called by concrete controllers."""
        for handler in self._handlers:
            handler(event)


class SimulatedInputController(InputController):
    """Software input source: inject events as if buttons were pressed.

    Example:
        controller = SimulatedInputController()
        controller.subscribe(print)
        controller.emit("NEXT_STATION")
    """

    def emit(self, event: str) -> None:
        self._dispatch(event)
