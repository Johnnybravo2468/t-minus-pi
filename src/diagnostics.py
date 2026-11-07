"""Short status codes for the LED board when a refresh is not healthy.

The panel has one spare text row under the station name. These codes use that
row so a failure is visible without covering the departure list. A healthy
refresh produces an empty string and the row stays blank.
"""

from __future__ import annotations

from typing import Optional

# Shown when the Pi has no default route (Wi-Fi down and Ethernet unplugged).
NO_LINK = "NO LINK"
# Shown when a route exists but the MBTA hostname does not resolve.
NO_DNS = "NO DNS"
# Timeouts, connection failures, and 5xx responses.
API_DOWN = "API DOWN"
# HTTP 429. The last good board stays on screen.
RATE_LIMIT = "RATE LIMIT"
# HTTP 401 or 403 from the MBTA API.
API_KEY = "API KEY"
# Any other fetch exception.
API_ERROR = "API ERROR"


def classify_fetch_error(message: Optional[str]) -> str:
    """Map an MBTA client error string to one panel code.

    ``get_route_departures`` stores ``str(exception)``. Matching that text
    keeps this module independent of the HTTP library.
    """
    if not message:
        return ""
    text = message.lower()
    if (
        "name or service not known" in text
        or "temporary failure in name resolution" in text
        or "nodename nor servname" in text
        or "name resolution" in text
    ):
        return NO_DNS
    if "429" in text or "too many requests" in text:
        return RATE_LIMIT
    if "401" in text or "403" in text or "unauthorized" in text or "forbidden" in text:
        return API_KEY
    if any(
        token in text
        for token in (
            "timeout",
            "timed out",
            "connect",
            "connection",
            "unreachable",
            "no route to host",
            "network is down",
            "502",
            "503",
            "504",
        )
    ):
        return API_DOWN
    return API_ERROR


def has_default_route(route_table: Optional[str] = None) -> Optional[bool]:
    """Return whether the kernel has an IPv4 default route.

    ``None`` means the routing table could not be read (for example on a
    non-Linux dev machine). Callers treat that as "unknown" and do not claim
    the link is down.
    """
    if route_table is None:
        try:
            with open("/proc/net/route", encoding="utf-8") as handle:
                route_table = handle.read()
        except OSError:
            return None
    for line in route_table.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "00000000":
            return True
    return False


def panel_status(error: Optional[str], link_up: Optional[bool]) -> str:
    """Pick the single code to draw for this refresh.

    A missing default route wins over the fetch error, because that is the
    cause (the Pi cannot reach DNS or the API). An empty fetch with no error
    is real "no service" and stays blank here.
    """
    if link_up is False:
        return NO_LINK
    return classify_fetch_error(error)
