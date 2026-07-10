"""Simulated Blue Robotics Ping2 echosounder, speaking the real Ping protocol.

Runs a UDP server that answers `brping` clients exactly like a Ping2 bridged
by BlueOS's ping service: COMMON_GENERAL_REQUEST in, the requested message
out. Depth comes from a synthetic bathymetry field evaluated at the vehicle's
live position (read from mavlink2rest), so a SITL survey sees spatially
coherent depth — and therefore swath width — variation, like a real seabed.
Without a position source it falls back to a slow time-based swell.

Run beside SITL:  python -m app.ping2_sim --port 9110
Point the extension at it:  SONAR_MODEL=ping2 PING_UDP=127.0.0.1:9110

This is a dev tool; on a real boat SONAR_MODEL=ping2 talks to the actual
device through the same adapter code this simulator exercises.
"""

from __future__ import annotations

import argparse
import logging
import math
import socket
import threading
import time

from brping import PingMessage, PingParser, definitions

from .telemetry import fetch_global_position, mav2rest_url

log = logging.getLogger("coverage.ping2sim")

HOME = (59.5945, 9.6708)  # Kongsberg SITL home; field is defined around it


def depth_at(lat: float, lon: float, home: tuple[float, float] = HOME) -> float:
    """Deterministic synthetic seabed: gentle slope + ridge field, 2–30 m."""
    y = (lat - home[0]) * 111_320.0
    x = (lon - home[1]) * 111_320.0 * math.cos(math.radians(home[0]))
    d = 9.0 + 0.015 * x + 2.0 * math.sin(x / 45.0) * math.cos(y / 70.0)
    return max(2.0, min(30.0, d))


class Ping2Simulator(threading.Thread):
    """UDP Ping-protocol responder. Daemon thread; stop() to shut down."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9110,
        confidence: int = 95,
        mav_url: str | None = "auto",  # "auto" -> telemetry default; None -> no position
    ) -> None:
        super().__init__(daemon=True, name="ping2-sim")
        self.confidence = confidence
        self.mav_url = mav2rest_url() if mav_url == "auto" else mav_url
        self.position: tuple[float, float] | None = None
        self._ping_number = 0
        self._t0 = time.monotonic()
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        self._sock.settimeout(0.2)
        self.address = self._sock.getsockname()  # resolved (host, port)

    # -- depth source -----------------------------------------------------
    def _update_position(self) -> None:
        if self.mav_url is None:
            return
        pos = fetch_global_position(self.mav_url)
        if pos and not (pos["lat"] == 0 and pos["lon"] == 0):
            self.position = (pos["lat"], pos["lon"])

    def current_depth_m(self) -> float:
        if self.position:
            return depth_at(*self.position)
        t = time.monotonic() - self._t0
        return 9.0 + 1.5 * math.sin(t / 20.0)  # no position: time-based swell

    # -- protocol ----------------------------------------------------------
    def _response_for(self, requested_id: int) -> PingMessage | None:
        try:
            msg = PingMessage(requested_id)
        except Exception:
            return None
        for field in msg.payload_field_names:
            setattr(msg, field, 0)
        if requested_id == definitions.COMMON_PROTOCOL_VERSION:
            msg.version_major, msg.version_minor, msg.version_patch = 1, 0, 0
        elif requested_id == definitions.COMMON_DEVICE_INFORMATION:
            msg.device_type = 1  # echosounder
            msg.device_revision = 2  # "Ping2"
            msg.firmware_version_major = 1
        elif requested_id == definitions.PING1D_GENERAL_INFO:
            msg.firmware_version_major = 1
            msg.ping_interval = 100
            msg.voltage_5 = 5000
        elif requested_id in (definitions.PING1D_DISTANCE, definitions.PING1D_DISTANCE_SIMPLE):
            self._ping_number += 1
            msg.distance = int(self.current_depth_m() * 1000)  # mm
            msg.confidence = self.confidence
            if requested_id == definitions.PING1D_DISTANCE:
                msg.ping_number = self._ping_number
                msg.scan_length = 30_000
        msg.pack_msg_data()
        return msg

    def run(self) -> None:
        parser = PingParser()
        last_pos_poll = 0.0
        log.info("ping2 sim on %s:%s (mav2rest: %s)", *self.address, self.mav_url)
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_pos_poll > 0.5:
                last_pos_poll = now
                self._update_position()
            try:
                data, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            for byte in data:
                if parser.parse_byte(byte) == PingParser.NEW_MESSAGE:
                    rx = parser.rx_msg
                    # Two request dialects: COMMON_GENERAL_REQUEST carries the
                    # wanted id in its payload; a "legacy request" is an empty
                    # message whose own id names what it wants (brping's
                    # Ping1D.initialize uses one of each).
                    if rx.message_id == definitions.COMMON_GENERAL_REQUEST:
                        resp = self._response_for(rx.requested_id)
                    elif rx.payload_length == 0:
                        resp = self._response_for(rx.message_id)
                    else:
                        resp = None
                    if resp is not None:
                        self._sock.sendto(resp.msg_data, addr)

    def stop(self) -> None:
        self._stop.set()
        self._sock.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulated Ping2 echosounder (UDP)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9110)
    ap.add_argument("--confidence", type=int, default=95)
    ap.add_argument("--no-position", action="store_true",
                    help="skip mavlink2rest; use time-based depth only")
    args = ap.parse_args()
    logging.basicConfig(level="INFO")
    sim = Ping2Simulator(args.host, args.port, args.confidence,
                         mav_url=None if args.no_position else "auto")
    sim.start()
    try:
        while True:
            time.sleep(5)
            d = sim.current_depth_m()
            log.info("depth %.1f m (position: %s)", d, sim.position or "none — time fallback")
    except KeyboardInterrupt:
        sim.stop()


if __name__ == "__main__":
    main()
