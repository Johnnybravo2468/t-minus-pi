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


def test_select_unknown_id_raises():
    m = StationManager(_stations("a", "b"))
    with pytest.raises(ValueError):
        m.select_station("zzz")


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
