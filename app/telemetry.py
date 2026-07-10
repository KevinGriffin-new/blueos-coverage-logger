"""Position poller: mavlink2rest -> track store.

Read-only: the extension never sends MAVLink, it only GETs message state
from BlueOS's mavlink2rest. GLOBAL_POSITION_INT carries position and heading;
time_boot_ms de-duplicates polls between vehicle updates.

MAV2REST_URL default works in both dev environments: on real BlueOS
(host-networked core) and on Docker Desktop for Mac (published port 6040),
``host.docker.internal`` resolves to where mavlink2rest listens. Outside a
container set MAV2REST_URL=http://localhost:6040.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request

from . import store
from .sonar import SonarAdapter, swath_width_m

log = logging.getLogger("coverage.telemetry")

DEFAULT_URL = "http://host.docker.internal:6040"
POLL_INTERVAL_S = 0.5


def mav2rest_url() -> str:
    return os.environ.get("MAV2REST_URL", DEFAULT_URL).rstrip("/")


def fetch_global_position(base_url: str, vehicle: int = 1, component: int = 1) -> dict | None:
    url = f"{base_url}/v1/mavlink/vehicles/{vehicle}/components/{component}/messages/GLOBAL_POSITION_INT"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            body = json.load(r)
    except Exception as e:  # noqa: BLE001 — any transport error means "no fix now"
        log.debug("mavlink2rest fetch failed: %s", e)
        return None
    msg = body.get("message") if isinstance(body, dict) else None
    if not msg or msg.get("lat") is None:
        return None
    return {
        "lat": msg["lat"] / 1e7,
        "lon": msg["lon"] / 1e7,
        "heading_deg": (msg.get("hdg", 0) or 0) / 100.0,
        "time_boot_ms": msg.get("time_boot_ms"),
    }


class Poller(threading.Thread):
    """Daemon thread: poll position, stamp with depth/swath, append to store."""

    def __init__(self, sonar: SonarAdapter) -> None:
        super().__init__(daemon=True, name="coverage-poller")
        self.sonar = sonar
        self.connected = False
        self.last_fix: dict | None = None
        self._last_boot_ms: int | None = None
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        conn = store.connect()  # this thread's own connection
        base = mav2rest_url()
        log.info("polling %s every %ss", base, POLL_INTERVAL_S)
        while not self._stop.wait(POLL_INTERVAL_S):
            pos = fetch_global_position(base)
            self.connected = pos is not None
            if pos is None:
                continue
            if pos["time_boot_ms"] is not None and pos["time_boot_ms"] == self._last_boot_ms:
                continue  # vehicle hasn't produced a newer message
            if pos["lat"] == 0 and pos["lon"] == 0:
                continue  # no GPS fix yet
            self._last_boot_ms = pos["time_boot_ms"]
            depth = self.sonar.depth_m()
            swath = swath_width_m(depth, self.sonar.beam_deg) if depth else None
            store.add_fix(
                conn,
                lat=pos["lat"],
                lon=pos["lon"],
                heading_deg=pos["heading_deg"],
                depth_m=depth,
                swath_m=swath,
            )
            self.last_fix = pos
