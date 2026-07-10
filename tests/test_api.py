from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DISABLE_POLLER", "1")
    import app.main as main

    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_register_service_fields(client):
    body = client.get("/register_service").json()
    assert body["name"] == "Coverage Logger"
    for key in ("description", "icon", "company", "version", "webpage", "api"):
        assert body[key]


def test_status_empty(client):
    st = client.get("/api/status").json()
    assert st["fix_count"] == 0
    assert st["sonar_model"] == "mock"
    assert st["connected"] is False
    assert st["plan_loaded"] is False


def test_track_grows_and_coverage_serves(client, tmp_path):
    from app import store
    from app.sonar import swath_width_m

    conn = store.connect()
    for i in range(5):
        store.add_fix(conn, lat=59.5945 + i * 1e-5, lon=9.6708, heading_deg=0.0,
                      depth_m=10.0, swath_m=swath_width_m(10.0, 25.0))
    conn.close()

    fixes = client.get("/api/track").json()["fixes"]
    assert len(fixes) == 5
    assert client.get("/api/track", params={"since_id": fixes[2]["id"]}).json()["fixes"] == fixes[3:]

    fc = client.get("/api/coverage.geojson").json()
    kinds = {f["properties"]["kind"] for f in fc["features"]}
    assert kinds == {"track", "coverage"}


def test_plan_upload_validation_and_holidays(client):
    bad = client.post("/api/plan", content=b"not json")
    assert bad.status_code == 422
    point = client.post("/api/plan", content=json.dumps({"type": "Point", "coordinates": [9.67, 59.59]}))
    assert point.status_code == 422

    ring = [[9.670, 59.594], [9.672, 59.594], [9.672, 59.595], [9.670, 59.595], [9.670, 59.594]]
    ok = client.post("/api/plan", content=json.dumps({"type": "Polygon", "coordinates": [ring]}))
    assert ok.status_code == 200
    assert client.get("/api/status").json()["plan_loaded"] is True

    from app import store
    from app.sonar import swath_width_m
    conn = store.connect()
    for i in range(4):
        store.add_fix(conn, lat=59.5945, lon=9.6705 + i * 1e-4, heading_deg=90.0,
                      depth_m=10.0, swath_m=swath_width_m(10.0, 25.0))
    conn.close()
    fc = client.get("/api/coverage.geojson").json()
    kinds = {f["properties"]["kind"] for f in fc["features"]}
    assert "holidays" in kinds


def test_clear_track(client):
    from app import store
    conn = store.connect()
    store.add_fix(conn, lat=1.0, lon=2.0, heading_deg=None, depth_m=None, swath_m=None)
    conn.close()
    assert client.get("/api/status").json()["fix_count"] == 1
    assert client.delete("/api/track").json() == {"ok": True}
    assert client.get("/api/status").json()["fix_count"] == 0


def test_index_and_vendored_leaflet(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Coverage Logger" in page.text
    assert client.get("/static/vendor/leaflet.js").status_code == 200
