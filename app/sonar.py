"""Sonar adapters: where depth comes from, and how wide the swath is.

The extension is read-only and sonar-agnostic. ``SONAR_MODEL`` picks the
adapter; ``mock`` (the default) needs no hardware and makes the whole
extension demonstrable against SITL. Real adapters (Ping2 via ping-python,
NMEA depth, Kongsberg TBD) plug in behind the same two members.

Beam angles are vendor-datasheet full beamwidths, mirroring survey-grid's
SONAR_PRESETS (single source of truth once survey-grid is on PyPI).
"""

from __future__ import annotations

import math
import os
import time
from typing import Protocol


class SonarAdapter(Protocol):
    model: str
    beam_deg: float  # FULL swath angle

    def depth_m(self) -> float | None:
        """Current depth under the vehicle, or None if unavailable."""
        ...


class MockAdapter:
    """Plausible depth without hardware: slow swell around a base depth.

    ``MOCK_DEPTH_M`` sets the base (default 10 m). The variation is time-based
    and deterministic, so coverage width visibly changes during a demo run.
    """

    model = "mock"

    def __init__(self, base_depth_m: float = 10.0, beam_deg: float = 25.0) -> None:
        self.base_depth_m = base_depth_m
        self.beam_deg = beam_deg
        self._t0 = time.monotonic()

    def depth_m(self) -> float | None:
        t = time.monotonic() - self._t0
        return self.base_depth_m * (1.0 + 0.15 * math.sin(t / 30.0))


class Ping2Adapter:
    """Blue Robotics Ping2 over the Ping protocol (UDP), via brping.

    Works against the real device (BlueOS's ping service bridges it to a UDP
    port on the vehicle) and against app.ping2_sim identically. ``PING_UDP``
    is ``host:port``; on a real boat something like
    ``host.docker.internal:9090``, in SITL dev ``127.0.0.1:9110``.

    Depth readings below ``min_confidence`` (device-reported, %) are treated
    as no-data rather than logged as bogus swath widths.
    """

    model = "ping2"
    beam_deg = 25.0  # Blue Robotics datasheet full beamwidth

    def __init__(self, udp: str, min_confidence: int = 50) -> None:
        from brping import Ping1D  # imported here: hardware adapters stay optional

        host, _, port = udp.partition(":")
        self._ping = Ping1D()
        self._ping.connect_udp(host, int(port or 9110))
        self.min_confidence = min_confidence
        self._initialized = self._try_initialize()

    def _try_initialize(self) -> bool:
        try:
            return bool(self._ping.initialize())
        except OSError:  # e.g. ConnectionRefusedError: nothing at that port yet
            return False

    def depth_m(self) -> float | None:
        if not self._initialized:
            self._initialized = self._try_initialize()  # device may come up late
            if not self._initialized:
                return None
        try:
            data = self._ping.get_distance()
        except OSError:
            self._initialized = False  # device went away; re-handshake next poll
            return None
        if not data or data.get("confidence", 0) < self.min_confidence:
            return None
        return data["distance"] / 1000.0


# model name -> adapter factory
_ADAPTERS = {
    "mock": lambda: MockAdapter(
        base_depth_m=float(os.environ.get("MOCK_DEPTH_M", "10")),
        beam_deg=float(os.environ.get("MOCK_BEAM_DEG", "25")),
    ),
    "ping2": lambda: Ping2Adapter(
        udp=os.environ.get("PING_UDP", "127.0.0.1:9110"),
        min_confidence=int(os.environ.get("PING_MIN_CONFIDENCE", "50")),
    ),
    # "s500": S500Adapter (beam 5°) — needs hardware or a Cerulean sim, later
}


def make_adapter(model: str | None = None) -> SonarAdapter:
    name = (model or os.environ.get("SONAR_MODEL", "mock")).lower()
    factory = _ADAPTERS.get(name)
    if factory is None:
        known = ", ".join(sorted(_ADAPTERS))
        raise ValueError(f"unknown SONAR_MODEL {name!r} — available: {known}")
    return factory()


def swath_width_m(depth_m: float, beam_deg: float) -> float:
    """Ensonified strip width: 2 · depth · tan(beam/2). beam_deg is FULL angle."""
    return 2.0 * depth_m * math.tan(math.radians(beam_deg) / 2.0)
