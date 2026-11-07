"""Tests for the Phase 2 StationManager (station selection state)."""

from pathlib import Path

import pytest

from src.config import RouteConfig, load_config
from src.station_manager import (
    DEFAULT_STATIONS,
    DisplayMode,
    StationManager,
    station_manager_from_config,
)
from src.phase2_console import EVENT_ACTIONS, apply_event


def _stations(*ids: str):
    return [
        RouteConfig(id=i, type="subway", route_id="Green-D", stop_id=f"stop-{i}", name=i.title())
        for i in ids
    ]


def test_requires_at_least_one_station():
    with pytest.raises(ValueError):
        StationManager([])


def test_starts_on_first_station():
    m = StationManager(_stations("a", "b", "c"))
    assert m.current_index == 0
    assert m.current_station().id == "a"
    assert m.station_count == 3


def test_next_station_wraps_around():
    m = StationManager(_stations("a", "b", "c"))
    assert m.next_station().id == "b"
    assert m.next_station().id == "c"
    assert m.next_station().id == "a"  # wraps


def test_previous_station_wraps_around():
    m = StationManager(_stations("a", "b", "c"))
    assert m.previous_station().id == "c"  # wraps backwards from first
    assert m.previous_station().id == "b"


def test_select_by_index_and_id():
    m = StationManager(_stations("a", "b", "c"))
    assert m.select_station(2).id == "c"
    assert m.select_station("a").id == "a"
    assert m.select_station(4).id == "b"  # index wraps (4 % 3 == 1)


def test_select_stop_prefers_the_requested_line():
    stations = [
        RouteConfig(id="Red:place-fenwy", type="subway", route_id="Red", stop_id="place-fenwy", name="Not Fenway"),
        RouteConfig(id="Green-B:place-pktrm", type="subway", route_id="Green-B", stop_id="place-pktrm", name="Park"),
        RouteConfig(id="Green-D:place-fenwy", type="subway", route_id="Green-D", stop_id="place-fenwy", name="Fenway"),
    ]
    m = StationManager(stations)
    assert m.current_station().id == "Red:place-fenwy"
    assert m.select_stop("place-fenwy", "GREEN-D") is True
    assert m.current_station().id == "Green-D:place-fenwy"
    assert m.select_stop("place-missing", "GREEN-D") is False
    assert m.current_station().id == "Green-D:place-fenwy"


def test_select_unknown_id_raises():
    m = StationManager(_stations("a", "b"))
    with pytest.raises(ValueError):
        m.select_station("zzz")


def _multiline():
    return [
        RouteConfig(id="g1", type="subway", route_id="Green-D", stop_id="s1", name="Green 1"),
        RouteConfig(id="g2", type="subway", route_id="Green-D", stop_id="s2", name="Green 2"),
        RouteConfig(id="r1", type="subway", route_id="Red", stop_id="s3", name="Red 1"),
        RouteConfig(id="cr", type="commuter_rail", route_id="CR-Worcester", stop_id="s4", name="CR"),
    ]


def test_current_line_family():
    m = StationManager(_multiline())
    assert m.current_line() == "GREEN-D"


def test_next_line_cycles_families_and_lands_on_first_of_line():
    m = StationManager(_multiline())
    assert m.next_line().id == "r1"       # GREEN -> RED (first red station)
    assert m.current_line() == "RED"
    assert m.next_line().id == "cr"       # RED -> COMMUTER
    assert m.current_line() == "COMMUTER"
    assert m.next_line().id == "g1"       # wraps to GREEN-D (first green station)


def test_next_line_single_line_is_noop():
    m = StationManager(_stations("a", "b", "c"))  # all Green-D
    assert m.next_line().id == "a"
    assert m.current_index == 0


def test_green_branches_cycle_as_separate_lines():
    stations = [
        RouteConfig(id="Green-B:park", type="subway", route_id="Green-B,Green-D", stop_id="park", name="Park B"),
        RouteConfig(id="Green-B:bc", type="subway", route_id="Green-B", stop_id="bc", name="Boston College"),
        RouteConfig(id="Green-D:park", type="subway", route_id="Green-B,Green-D", stop_id="park", name="Park D"),
        RouteConfig(id="Green-D:fenway", type="subway", route_id="Green-D", stop_id="fenway", name="Fenway"),
        RouteConfig(id="Red:dtx", type="subway", route_id="Red", stop_id="dtx", name="Downtown Crossing"),
    ]
    m = StationManager(stations)
    assert m.current_line() == "GREEN-B"
    assert m.next_station().id == "Green-B:bc"
    assert m.next_station().id == "Green-B:park"  # stays on B, not the D copy of Park
    assert m.next_line().id == "Green-D:park"
    assert m.current_line() == "GREEN-D"
    assert m.next_line().id == "Red:dtx"
    assert m.current_line() == "RED"


def test_bus_button_switches_service_and_remembers_the_stop():
    stations = _multiline() + [
        RouteConfig(id="47:1807", type="bus", route_id="47", stop_id="1807", name="Park Dr at Fenway"),
        RouteConfig(id="47:1806", type="bus", route_id="47", stop_id="1806", name="Brookline Ave at Fenway"),
        RouteConfig(id="9:175", type="bus", route_id="9", stop_id="175", name="Copley"),
    ]
    m = StationManager(stations)
    m.next_station()  # second Green-D stop
    assert m.current_station().id == "g2"
    assert m.switch_service().id == "47:1807"
    assert m.service_mode() == "bus"
    assert m.next_station().id == "47:1806"
    assert m.next_line().id == "9:175"          # 47 -> 9, not back to the subway
    assert m.current_line() == "BUS-9"
    assert m.switch_service().id == "g2"        # back to the subway stop we left
    assert m.service_mode() == "rail"
    assert m.switch_service().id == "9:175"     # bus side remembers Copley


def test_next_line_does_not_enter_bus_routes():
    stations = _multiline() + [
        RouteConfig(id="47:1807", type="bus", route_id="47", stop_id="1807", name="Park Dr"),
    ]
    m = StationManager(stations)
    seen = []
    for _ in range(6):
        seen.append(m.current_line())
        m.next_line()
    assert seen[:4] == ["GREEN-D", "RED", "COMMUTER", "GREEN-D"]
    assert "BUS-47" not in seen


def test_next_station_stays_within_current_line():
    # Two green stops, then two red stops.
    stations = [
        RouteConfig(id="g1", type="subway", route_id="Green-D", stop_id="s1", name="G1"),
        RouteConfig(id="g2", type="subway", route_id="Green-D", stop_id="s2", name="G2"),
        RouteConfig(id="r1", type="subway", route_id="Red", stop_id="s3", name="R1"),
        RouteConfig(id="r2", type="subway", route_id="Red", stop_id="s4", name="R2"),
    ]
    m = StationManager(stations)
    assert m.next_station().id == "g2"     # within green
    assert m.next_station().id == "g1"     # wraps within green (not into red)
    m.next_line()                          # jump to red
    assert m.current_station().id == "r1"
    assert m.next_station().id == "r2"     # within red
    assert m.next_station().id == "r1"     # wraps within red


def test_toggle_mode_flips():
    m = StationManager(_stations("a"))
    assert m.mode is DisplayMode.NORMAL
    assert m.toggle_mode() is DisplayMode.STATION_SELECT
    assert m.toggle_mode() is DisplayMode.NORMAL


def test_from_config_falls_back_to_defaults(tmp_path: Path, monkeypatch):
    # No config.yaml / no stations configured -> built-in defaults.
    monkeypatch.chdir(tmp_path)
    m = station_manager_from_config()
    assert m.station_count == len(DEFAULT_STATIONS)
    assert m.current_station().id == "fenway_green_d"


def test_load_config_reads_stations(tmp_path: Path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        """
stations:
  - id: "s1"
    type: "subway"
    route_id: "Green-D"
    stop_id: "place-fenwy"
    name: "Fenway"
  - id: "s2"
    type: "subway"
    route_id: "Green-D"
    stop_id: "place-kencl"
    name: "Kenmore"
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path=yaml_file, env_path=tmp_path / ".env")
    assert [s.id for s in cfg.stations] == ["s1", "s2"]

    m = station_manager_from_config(cfg)
    assert m.station_count == 2
    assert m.current_station().name == "Fenway"


def test_event_dispatch_drives_manager():
    m = StationManager(_stations("a", "b", "c"))
    apply_event(m, "NEXT_STATION")
    assert m.current_station().id == "b"
    apply_event(m, "PREVIOUS_STATION")
    assert m.current_station().id == "a"
    apply_event(m, "TOGGLE")
    assert m.mode is DisplayMode.STATION_SELECT
    # Unknown events are ignored, not fatal.
    apply_event(m, "NONSENSE")
    assert m.current_station().id == "a"
    assert set(EVENT_ACTIONS) == {"NEXT_STATION", "PREVIOUS_STATION", "TOGGLE", "BUTTON_3"}
