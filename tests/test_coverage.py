from __future__ import annotations

import math

import pytest
from pyproj import CRS, Transformer
from shapely.geometry import shape

from app.coverage import coverage_geojson

LAT0, LON0 = 59.5945, 9.6708


def _fixes_along_east(n: int, step_m: float, swath_m: float | None) -> list[dict]:
    """Straight east track starting at (LAT0, LON0)."""
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={LAT0} +lon_0={LON0} +units=m")
    to_ll = Transformer.from_crs(aeqd, "EPSG:4326", always_xy=True)
    fixes = []
    for i in range(n):
        lon, lat = to_ll.transform(i * step_m, 0)
        fixes.append({"lat": lat, "lon": lon, "swath_m": swath_m})
    return fixes


def _feature(fc: dict, kind: str) -> dict | None:
    return next((f for f in fc["features"] if f["properties"]["kind"] == kind), None)


def test_empty_and_single_fix_yield_no_features():
    assert coverage_geojson([]) == {"type": "FeatureCollection", "features": []}
    assert coverage_geojson(_fixes_along_east(1, 10, 20))["features"] == []


def test_track_and_coverage_area():
    # 100 m straight track, 20 m swath -> corridor ~ 100*20 plus rounded ends
    fixes = _fixes_along_east(11, 10.0, 20.0)
    fc = coverage_geojson(fixes)
    track = _feature(fc, "track")
    cov = _feature(fc, "coverage")
    assert track is not None and cov is not None
    assert track["properties"]["fixes"] == 11
    end_caps = math.pi * 10.0**2  # buffer() round caps, r = swath/2
    assert cov["properties"]["area_m2"] == pytest.approx(100 * 20 + end_caps, rel=0.02)


def test_no_swath_means_track_only():
    fc = coverage_geojson(_fixes_along_east(5, 10.0, None))
    assert _feature(fc, "track") is not None
    assert _feature(fc, "coverage") is None


def test_holidays_subtract_coverage_from_plan():
    # Plan: 100 x 40 m box centred on the track; one pass covers a 20 m strip
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={LAT0} +lon_0={LON0} +units=m")
    to_ll = Transformer.from_crs(aeqd, "EPSG:4326", always_xy=True)
    ring = [list(to_ll.transform(x, y)) for x, y in
            [(0, -20), (100, -20), (100, 20), (0, 20), (0, -20)]]
    plan = {"type": "Polygon", "coordinates": [ring]}

    fc = coverage_geojson(_fixes_along_east(11, 10.0, 20.0), plan)
    hol = _feature(fc, "holidays")
    assert hol is not None
    assert hol["properties"]["plan_area_m2"] == pytest.approx(4000, rel=0.01)
    # Covered strip inside the plan is ~100x20 -> holidays ~2000 m^2 (caps stick out)
    assert hol["properties"]["area_m2"] == pytest.approx(2000, rel=0.05)
    assert hol["properties"]["covered_pct"] == pytest.approx(50.0, abs=2.5)
    # Geometry sanity: holiday area lies inside the plan
    assert shape(hol["geometry"]).within(shape(plan).buffer(1e-9))


def test_swath_width_varies_per_segment():
    fixes = _fixes_along_east(3, 50.0, 10.0)
    fixes[2]["swath_m"] = 30.0  # second segment averages (10+30)/2 = 20
    fc = coverage_geojson(fixes)
    cov = _feature(fc, "coverage")
    # Strips alone: 50·10 + 50·20 = 1500; round caps (r=5 and r=10) add up to
    # ~2 half-discs + the joint bulge. Assert the widths were actually applied
    # per segment (a uniform 10 m corridor would be ~1080, uniform 20 m ~2310).
    assert 1500 < cov["properties"]["area_m2"] < 1950
