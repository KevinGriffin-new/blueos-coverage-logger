"""Coverage Logger — a read-only BlueOS extension.

Logs the vehicle track from mavlink2rest, stamps each fix with sonar depth
and swath width, and serves a live map of coverage and gaps ("holidays").
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import coverage, store, telemetry
from .sonar import make_adapter

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

VERSION = "0.1.0"
STATIC = Path(__file__).parent / "static"

sonar = make_adapter()
poller = telemetry.Poller(sonar)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("DISABLE_POLLER") != "1":  # tests set this
        poller.start()
    yield
    poller.stop()


app = FastAPI(title="Coverage Logger", version=VERSION, lifespan=lifespan)


@app.get("/register_service")
def register_service() -> JSONResponse:
    """BlueOS service registration: how the extension appears in the UI."""
    return JSONResponse(
        {
            "name": "Coverage Logger",
            "description": "Survey coverage logger: live track, swath footprint, and gap flags",
            "icon": "mdi-map-check",
            "company": "Kevin Griffin",
            "version": VERSION,
            "webpage": "https://github.com/KevinGriffin-new/blueos-coverage-logger",
            "api": "/docs",
        }
    )


@app.get("/api/status")
def status() -> dict:
    conn = store.connect()
    try:
        return {
            "mavlink2rest": telemetry.mav2rest_url(),
            "connected": poller.connected,
            "sonar_model": sonar.model,
            "beam_deg": sonar.beam_deg,
            "depth_m": sonar.depth_m(),
            "fix_count": store.fix_count(conn),
            "last_fix": poller.last_fix,
            "plan_loaded": store.get_plan(conn) is not None,
        }
    finally:
        conn.close()


@app.get("/api/track")
def track(since_id: int = 0) -> dict:
    conn = store.connect()
    try:
        fixes = store.fixes_since(conn, since_id)
    finally:
        conn.close()
    return {"fixes": fixes}


@app.get("/api/coverage.geojson")
def coverage_geojson() -> dict:
    conn = store.connect()
    try:
        fixes = store.fixes_since(conn)
        plan_raw = store.get_plan(conn)
    finally:
        conn.close()
    plan = json.loads(plan_raw) if plan_raw else None
    return coverage.coverage_geojson(fixes, plan)


@app.post("/api/plan")
async def set_plan(request: Request) -> dict:
    body = await request.body()
    try:
        parsed = json.loads(body)
        coverage._plan_polygon(parsed)  # validate before storing
    except (json.JSONDecodeError, ValueError, KeyError, IndexError) as e:
        raise HTTPException(status_code=422, detail=f"not a usable plan polygon: {e}")
    conn = store.connect()
    try:
        store.set_plan(conn, json.dumps(parsed))
    finally:
        conn.close()
    return {"ok": True}


@app.delete("/api/track")
def clear_track() -> dict:
    """Reset the logged track (e.g. between survey runs)."""
    conn = store.connect()
    try:
        store.clear_track(conn)
    finally:
        conn.close()
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
