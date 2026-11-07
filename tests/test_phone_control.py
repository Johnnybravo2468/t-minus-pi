"""Tests for the phone button page."""

import json
import queue
import urllib.error
import urllib.request

from src.phone_control import PhoneControl, start_phone_server


def test_press_accepts_station_keys_only():
    commands: queue.Queue = queue.Queue()
    control = PhoneControl(commands)
    assert control.press("N") is True
    assert control.press("p") is True
    assert control.press("t") is True
    assert control.press("q") is False
    assert control.press("nope") is False
    assert [commands.get_nowait() for _ in range(3)] == ["n", "p", "t"]
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

        with urllib.request.urlopen(base + "/api/state") as response:
            state = json.loads(response.read().decode("utf-8"))
        assert state == {"name": "Fenway (D)", "line": "GREEN-D", "status": "NO LINK"}

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
