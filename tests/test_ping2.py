"""Ping2Adapter exercised against the protocol-level simulator over loopback."""

from __future__ import annotations

import pytest

from app.ping2_sim import HOME, Ping2Simulator, depth_at
from app.sonar import Ping2Adapter, make_adapter


@pytest.fixture()
def sim():
    s = Ping2Simulator(host="127.0.0.1", port=0, mav_url=None)  # ephemeral port, no position
    s.start()
    yield s
    s.stop()


def test_adapter_reads_depth_through_ping_protocol(sim):
    adapter = Ping2Adapter(udp=f"127.0.0.1:{sim.address[1]}")
    assert adapter._initialized, "initialize() should get a PROTOCOL_VERSION reply"
    d = adapter.depth_m()
    assert d is not None
    assert 7.0 <= d <= 11.0  # time-fallback swell: 9 ± 1.5
    assert adapter.model == "ping2"
    assert adapter.beam_deg == 25.0


def test_low_confidence_is_rejected():
    s = Ping2Simulator(host="127.0.0.1", port=0, confidence=10, mav_url=None)
    s.start()
    try:
        adapter = Ping2Adapter(udp=f"127.0.0.1:{s.address[1]}", min_confidence=50)
        assert adapter.depth_m() is None
    finally:
        s.stop()


def test_adapter_survives_missing_device():
    # Nothing listening: initialize fails, depth_m returns None, no exception.
    adapter = Ping2Adapter(udp="127.0.0.1:1")  # port 1: nothing there
    assert adapter._initialized is False
    assert adapter.depth_m() is None


def test_make_adapter_ping2_env(monkeypatch, sim):
    monkeypatch.setenv("SONAR_MODEL", "ping2")
    monkeypatch.setenv("PING_UDP", f"127.0.0.1:{sim.address[1]}")
    a = make_adapter()
    assert a.model == "ping2"
    assert a.depth_m() is not None


def test_bathymetry_field_is_deterministic_and_bounded():
    assert depth_at(*HOME) == depth_at(*HOME)
    lat0, lon0 = HOME
    depths = [
        depth_at(lat0 + dy * 1e-5, lon0 + dx * 1e-5)
        for dy in range(-30, 30, 3)
        for dx in range(-30, 30, 3)
    ]
    assert all(2.0 <= d <= 30.0 for d in depths)
    assert max(depths) - min(depths) > 1.0, "field should actually vary"


def test_position_drives_depth(sim):
    sim.position = HOME
    d_home = sim.current_depth_m()
    sim.position = (HOME[0], HOME[1] + 0.002)  # ~113 m east
    d_east = sim.current_depth_m()
    assert d_home == pytest.approx(depth_at(*HOME))
    assert d_east != pytest.approx(d_home)
