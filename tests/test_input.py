"""Tests for the Phase 4 input controller and app controller (state machine)."""

from src.app_controller import AppController
from src.config import RouteConfig
from src.input_controller import (
    KNOWN_EVENTS,
    NEXT_STATION,
    PREVIOUS_STATION,
    SimulatedInputController,
    TOGGLE,
)
from src.station_manager import StationManager


def _stations(*ids: str):
    return [
        RouteConfig(id=i, type="subway", route_id="Green-D", stop_id=f"stop-{i}", name=i.title())
        for i in ids
    ]


def _multiline_stations():
    return [
        RouteConfig(id="g", type="subway", route_id="Green-D", stop_id="s1", name="Green"),
        RouteConfig(id="r", type="subway", route_id="Red", stop_id="s2", name="Red"),
        RouteConfig(id="b", type="subway", route_id="Blue", stop_id="s3", name="Blue"),
    ]


def test_simulated_input_dispatches_to_subscribers():
    received = []
    controller = SimulatedInputController()
    controller.subscribe(received.append)
    controller.emit(NEXT_STATION)
    controller.emit(TOGGLE)
    assert received == [NEXT_STATION, TOGGLE]


def test_multiple_subscribers_all_notified():
    a, b = [], []
    controller = SimulatedInputController()
    controller.subscribe(a.append)
    controller.subscribe(b.append)
    controller.emit(NEXT_STATION)
    assert a == [NEXT_STATION]
    assert b == [NEXT_STATION]


def test_app_controller_maps_events_to_station_actions():
    manager = StationManager(_stations("a", "b", "c"))
    controller = AppController(manager)

    controller.handle_event(NEXT_STATION)
    assert manager.current_station().id == "b"
    controller.handle_event(PREVIOUS_STATION)
    assert manager.current_station().id == "a"


def test_toggle_event_cycles_lines():
    manager = StationManager(_multiline_stations())
    controller = AppController(manager)
    assert manager.current_line() == "GREEN"
    controller.handle_event(TOGGLE)
    assert manager.current_line() == "RED"
    controller.handle_event(TOGGLE)
    assert manager.current_line() == "BLUE"
    controller.handle_event(TOGGLE)
    assert manager.current_line() == "GREEN"  # wraps


def test_app_controller_ignores_unknown_event():
    manager = StationManager(_stations("a", "b"))
    controller = AppController(manager)
    controller.handle_event("NONSENSE")  # must not raise
    assert manager.current_station().id == "a"


def test_on_change_callback_receives_event_and_manager():
    manager = StationManager(_stations("a", "b"))
    seen = []
    controller = AppController(manager, on_change=lambda e, m: seen.append((e, m.current_station().id)))
    controller.handle_event(NEXT_STATION)
    assert seen == [(NEXT_STATION, "b")]


def test_end_to_end_input_drives_station_manager():
    manager = StationManager(_stations("a", "b", "c"))
    controller = AppController(manager)
    inputs = SimulatedInputController()
    controller.connect(inputs)

    inputs.emit(NEXT_STATION)
    inputs.emit(NEXT_STATION)
    assert manager.current_station().id == "c"
    inputs.emit(PREVIOUS_STATION)
    assert manager.current_station().id == "b"


def test_known_events_set():
    assert KNOWN_EVENTS == {"NEXT_STATION", "PREVIOUS_STATION", "TOGGLE", "BUTTON_3"}
