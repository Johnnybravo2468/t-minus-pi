"""Phone controls for the LED board on the local network.

A small web page on the Pi's LAN address has the same buttons as the keyboard:
previous station, next station, and next line. Any phone on the same network
can open the page. Nothing here is exposed beyond that network by itself.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

# Keys the page is allowed to send. Quit stays on the keyboard so a tap
# cannot shut the board down.
PHONE_KEYS = {"n", "p", "t"}

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>t-minus-pi</title>
  <style>
    body { margin: 0; background: #111; color: #f2f2f2;
           font-family: system-ui, sans-serif; }
    header { padding: 1.25rem 1rem 0.25rem; }
    h1 { font-size: 1.7rem; margin: 0; }
    p { margin: 0.4rem 0 0; color: #9ad; min-height: 1.2em; }
    .fault { color: #f80; }
    button { display: block; width: calc(100% - 2rem); margin: 0.75rem 1rem;
             padding: 1.15rem; font-size: 1.35rem; border: 0; border-radius: 14px;
             background: #2a2a2a; color: white; }
    button.primary { background: #0b7a4b; }
  </style>
</head>
<body>
  <header>
    <h1 id="station">Loading…</h1>
    <p id="detail"></p>
  </header>
  <button type="button" onclick="act('p')">Previous station</button>
  <button class="primary" type="button" onclick="act('n')">Next station</button>
  <button type="button" onclick="act('t')">Next line</button>
  <script>
    async function refresh() {
      const response = await fetch("/api/state");
      const state = await response.json();
      document.getElementById("station").textContent = state.name || "…";
      const detail = document.getElementById("detail");
      detail.textContent = state.status || state.line || "";
      detail.className = state.status ? "fault" : "";
    }
    async function act(key) {
      await fetch("/api/action", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({key})
      });
      setTimeout(refresh, 400);
      setTimeout(refresh, 1200);
    }
    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""


class PhoneControl:
    """Shared station label and the queue of button presses."""

    def __init__(self, commands: queue.Queue):
        self.commands = commands
        self._lock = threading.Lock()
        self.name = ""
        self.line = ""
        self.status = ""

    def update(self, name: str, line: str, status: str) -> None:
        with self._lock:
            self.name = name
            self.line = line
            self.status = status

    def snapshot(self) -> dict:
        with self._lock:
            return {"name": self.name, "line": self.line, "status": self.status}

    def press(self, key: str) -> bool:
        """Queue a button press. Unknown keys are ignored."""
        cleaned = (key or "").strip().lower()
        if cleaned not in PHONE_KEYS:
            return False
        self.commands.put(cleaned)
        return True


def lan_ip() -> str:
    """Best-guess address a phone on the same network can use to reach the Pi."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.168.0.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def start_phone_server(
    control: PhoneControl,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> Optional[ThreadingHTTPServer]:
    """Serve the button page in a background thread. Returns None if the port is taken."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/state":
                body = json.dumps(control.snapshot()).encode("utf-8")
                self._send(200, body, "application/json")
                return
            self.send_error(404)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/action":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            try:
                key = json.loads(raw.decode("utf-8") or "{}").get("key", "")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_error(400)
                return
            if not control.press(str(key)):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"Phone controls did not start: {exc}", flush=True)
        return None
    threading.Thread(target=server.serve_forever, name="led-phone", daemon=True).start()
    return server
