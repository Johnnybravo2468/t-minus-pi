"""Tests for the phone button page."""

import json
import queue
import socket
import urllib.error
import urllib.request

import pytest

from src.phone_control import (
    PhoneControl,
    line_label,
    phone_url,
    preferred_lan_ip,
    start_phone_server,
)


def test_stable_service_points_at_the_fixed_name():
    pytest.importorskip("zeroconf")
    from src.phone_control import stable_service

    info = stable_service(8080, "192.168.0.23")
    assert info.server == "t-minus-pi.local."
    assert info.port == 8080
    assert socket.inet_ntoa(info.addresses[0]) == "192.168.0.23"


def test_avahi_command_uses_the_fixed_name(monkeypatch):
    from src import phone_control

    monkeypatch.setattr(phone_control.shutil, "which", lambda name: "/usr/bin/avahi-publish" if name == "avahi-publish" else None)
    assert phone_control.avahi_publish_command("192.168.0.23") == [
        "avahi-publish",
        "-a",
        "-R",
        "t-minus-pi.local",
        "192.168.0.23",
    ]


def test_line_label_reads_as_a_person_would():
    assert line_label("GREEN-D") == "Green D"
    assert line_label("RED") == "Red Line"
    assert line_label("ORANGE") == "Orange Line"
    assert line_label("BLUE") == "Blue Line"
    assert line_label("COMMUTER") == "Commuter rail"
    assert line_label("BUS-47", "bus") == "Route 47"
    assert line_label("BUS-9", "bus") == "Route 9"


def test_phone_url_stays_fixed():
    assert phone_url() == "http://t-minus-pi.local:8080"
    assert phone_url(9000) == "http://t-minus-pi.local:9000"


def test_preferred_lan_ip_picks_the_home_network():
    assert preferred_lan_ip(["127.0.0.1", "169.254.1.1", "192.168.0.23"]) == "192.168.0.23"
    assert preferred_lan_ip(["10.0.0.5", "192.168.0.23"]) == "10.0.0.5"
    assert preferred_lan_ip(["127.0.0.1", "0.0.0.0"]) is None
    assert preferred_lan_ip([]) is None


def test_press_accepts_station_keys_only():
    commands: queue.Queue = queue.Queue()
    control = PhoneControl(commands)
    assert control.press("N") is True
    assert control.press("p") is True
    assert control.press("t") is True
    assert control.press("B") is True
    assert control.press("q") is False
    assert control.press("nope") is False
    assert [commands.get_nowait() for _ in range(4)] == ["n", "p", "t", "b"]
    assert commands.empty()


def test_phone_page_serves_buttons_and_queues_them():
    commands: queue.Queue = queue.Queue()
    control = PhoneControl(commands)
    control.update("Fenway (D)", "GREEN-D", "NO LINK")
    server = start_phone_server(control, host="127.0.0.1", port=0)
    assert server is not None
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/") as response:
            page = response.read().decode("utf-8")
        assert "Next station" in page
        assert "Previous station" in page
        assert "Next line" in page
        assert "Subway" in page
        assert "Bus" in page

        with urllib.request.urlopen(base + "/api/state") as response:
            state = json.loads(response.read().decode("utf-8"))
        assert state == {
            "name": "Fenway (D)",
            "line": "GREEN-D",
            "label": "Green D",
            "status": "NO LINK",
            "mode": "rail",
        }

        request = urllib.request.Request(
            base + "/api/action",
            data=json.dumps({"key": "t"}).encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 204
        assert commands.get_nowait() == "t"

        rejected = urllib.request.Request(
            base + "/api/action",
            data=json.dumps({"key": "q"}).encode("utf-8"),
            method="POST",
        )
        try:
            urllib.request.urlopen(rejected)
            raise AssertionError("quit should not be accepted from the phone")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        assert commands.empty()
    finally:
        server.shutdown()
