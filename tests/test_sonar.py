from __future__ import annotations

import math

import pytest

from app.sonar import MockAdapter, make_adapter, swath_width_m


def test_swath_width_full_angle():
    assert swath_width_m(10.0, 90.0) == pytest.approx(20.0)
    assert swath_width_m(5.0, 60.0) == pytest.approx(2 * 5 * math.tan(math.radians(30)), abs=1e-9)


def test_mock_adapter_depth_near_base():
    a = MockAdapter(base_depth_m=10.0)
    d = a.depth_m()
    assert 8.0 <= d <= 12.0
    assert a.model == "mock"
    assert a.beam_deg == 25.0


def test_make_adapter_env(monkeypatch):
    monkeypatch.setenv("SONAR_MODEL", "mock")
    monkeypatch.setenv("MOCK_DEPTH_M", "7.5")
    monkeypatch.setenv("MOCK_BEAM_DEG", "5")
    a = make_adapter()
    assert a.base_depth_m == 7.5
    assert a.beam_deg == 5.0


def test_make_adapter_unknown():
    with pytest.raises(ValueError, match="available"):
        make_adapter("kraken-9000")
