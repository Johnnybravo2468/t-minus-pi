"""Phone controls for the LED board on the local network.

A small web page has the same buttons as the keyboard: previous station, next
station, and next line. While the program is running the page answers at one
fixed name, ``http://t-minus-pi.local:8080``, even when the Pi's numeric
address changes. Any phone on the same network can open it. Nothing here is
exposed beyond that network by itself.
"""

from __future__ import annotations

import json
import queue
import shutil
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

# Bookmark this. The name is announced only while this program is running.
STABLE_HOST = "t-minus-pi.local"
# Held so the announcer is not garbage-collected while the board is up.
_ANNOUNCER = None

# Keys the page is allowed to send. Quit stays on the keyboard so a tap
# cannot shut the board down.
PHONE_KEYS = {"n", "p", "t", "b"}

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
  <button type="button" id="mode" onclick="act('b')">Bus routes</button>
  <script>
    async function refresh() {
      const response = await fetch("/api/state");
      const state = await response.json();
      document.getElementById("station").textContent = state.name || "…";
      const detail = document.getElementById("detail");
      detail.textContent = state.status || state.line || "";
      detail.className = state.status ? "fault" : "";
      const mode = document.getElementById("mode");
      mode.textContent = state.mode === "bus" ? "Subway" : "Bus routes";
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
        self.mode = "rail"

    def update(self, name: str, line: str, status: str, mode: str = "rail") -> None:
        with self._lock:
            self.name = name
            self.line = line
            self.status = status
            self.mode = mode or "rail"

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "line": self.line,
                "status": self.status,
                "mode": self.mode,
            }

    def press(self, key: str) -> bool:
        """Queue a button press. Unknown keys are ignored."""
        cleaned = (key or "").strip().lower()
        if cleaned not in PHONE_KEYS:
            return False
        self.commands.put(cleaned)
        return True


def phone_url(port: int = 8080) -> str:
    """The address that stays the same across reboots and DHCP changes."""
    return f"http://{STABLE_HOST}:{port}"


def _is_private(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(part) for part in parts]
    except ValueError:
        return False
    if any(octet < 0 or octet > 255 for octet in octets):
        return False
    if octets[0] == 10:
        return True
    if octets[0] == 192 and octets[1] == 168:
        return True
    return octets[0] == 172 and 16 <= octets[1] <= 31


def _routed_ipv4() -> Optional[str]:
    """Source address the kernel would use to reach the wider network."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def interface_ipv4_addresses() -> list[str]:
    """IPv4 addresses currently assigned to real interfaces."""
    try:
        import fcntl
    except ImportError:
        return []
    found: list[str] = []
    try:
        names = socket.if_nameindex()
    except OSError:
        return found
    for _index, name in names:
        if name == "lo":
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = fcntl.ioctl(
                sock.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack("256s", name.encode("utf-8")[:15]),
            )
        except OSError:
            continue
        finally:
            sock.close()
        found.append(socket.inet_ntoa(packed[20:24]))
    return found


def preferred_lan_ip(addresses: Optional[list[str]] = None) -> Optional[str]:
    """Address a phone on the home network can reach. Loopback is never chosen."""
    routed = None
    if addresses is None:
        routed = _routed_ipv4()
        addresses = list(interface_ipv4_addresses())
        if routed and routed not in addresses:
            addresses.insert(0, routed)
    private = [ip for ip in addresses if _is_private(ip)]
    if routed and routed in private:
        return routed
    if private:
        return private[0]
    for ip in addresses:
        if ip and not ip.startswith("127.") and ip != "0.0.0.0":
            return ip
    return None


def lan_ip() -> str:
    """Best-guess address a phone on the same network can use to reach the Pi."""
    return preferred_lan_ip() or "127.0.0.1"


def stable_service(port: int, address: str):
    """mDNS record that points the fixed name at this machine."""
    from zeroconf import ServiceInfo

    return ServiceInfo(
        "_http._tcp.local.",
        "T-Minus Pi._http._tcp.local.",
        addresses=[socket.inet_aton(address)],
        port=port,
        server=f"{STABLE_HOST}.",
        properties={"path": "/"},
    )


def avahi_publish_command(address: str) -> Optional[list[str]]:
    """Command that asks the Pi's Avahi daemon to publish the fixed name."""
    if shutil.which("avahi-publish"):
        return ["avahi-publish", "-a", "-R", STABLE_HOST, address]
    if shutil.which("avahi-publish-address"):
        return ["avahi-publish-address", "-R", STABLE_HOST, address]
    return None


def _announce_with_zeroconf(port: int, address: str) -> tuple[bool, str]:
    global _ANNOUNCER
    try:
        from zeroconf import IPVersion, Zeroconf
    except ImportError:
        return False, "zeroconf is not installed"
    announcer = None
    try:
        announcer = Zeroconf(ip_version=IPVersion.V4Only)
        announcer.register_service(stable_service(port, address))
    except Exception as exc:
        if announcer is not None:
            announcer.close()
        return False, str(exc)
    _ANNOUNCER = announcer
    return True, ""


def _announce_with_avahi(address: str) -> tuple[bool, str]:
    """Publish through Avahi when it already owns the mDNS port."""
    global _ANNOUNCER
    import subprocess
    import time

    command = avahi_publish_command(address)
    if command is None:
        return False, "avahi-publish is not installed"
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(0.4)
    if proc.poll() is not None:
        detail = proc.stderr.read().decode("utf-8", "replace").strip() if proc.stderr else ""
        return False, detail or "avahi-publish exited"
    _ANNOUNCER = proc
    return True, ""


def advertise_stable_name(port: int, address: str) -> bool:
    """Tell the local network that ``t-minus-pi.local`` is this Pi, until exit."""
    # On the Pi, Avahi already owns multicast DNS. Publish through it when
    # the helper is installed, and use the Python announcer otherwise.
    avahi_error = ""
    if avahi_publish_command(address):
        ok, avahi_error = _announce_with_avahi(address)
        if ok:
            return True
    ok, zeroconf_error = _announce_with_zeroconf(port, address)
    if ok:
        return True
    if avahi_error:
        print(f"Phone name was not announced: {avahi_error}", flush=True)
    print(f"Phone name was not announced: {zeroconf_error}", flush=True)
    if "Address already in use" in zeroconf_error or "Errno 98" in zeroconf_error:
        print("Install the Pi helper with: sudo apt install -y avahi-utils", flush=True)
    else:
        print("Install it once with: .venv/bin/pip install zeroconf", flush=True)
    return False


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
