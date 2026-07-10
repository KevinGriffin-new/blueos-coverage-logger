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


# model name -> (adapter factory, full beam angle)
_ADAPTERS = {
    "mock": lambda: MockAdapter(
        base_depth_m=float(os.environ.get("MOCK_DEPTH_M", "10")),
        beam_deg=float(os.environ.get("MOCK_BEAM_DEG", "25")),
    ),
    # "ping2": Ping2Adapter (beam 25°, ping-python) — needs hardware, Phase 3
    # "s500": S500Adapter (beam 5°) — needs hardware, Phase 3
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
