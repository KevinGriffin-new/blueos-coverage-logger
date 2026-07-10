"""SQLite track store. One row per position fix.

WAL mode so the poller thread writes while API requests read with their own
connections. The database lives in DATA_DIR (the extension's /data bind on
BlueOS; ./data during development).
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    heading_deg REAL,
    depth_m REAL,
    swath_m REAL
);
CREATE TABLE IF NOT EXISTS plan (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    geojson TEXT NOT NULL
);
"""


def data_dir() -> Path:
    d = Path(os.environ.get("DATA_DIR", "./data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "coverage.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def add_fix(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    heading_deg: float | None,
    depth_m: float | None,
    swath_m: float | None,
    ts: float | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO fixes (ts, lat, lon, heading_deg, depth_m, swath_m) VALUES (?,?,?,?,?,?)",
        (ts if ts is not None else time.time(), lat, lon, heading_deg, depth_m, swath_m),
    )
    conn.commit()
    return cur.lastrowid


def fixes_since(conn: sqlite3.Connection, since_id: int = 0, limit: int = 100_000) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM fixes WHERE id > ? ORDER BY id LIMIT ?", (since_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def fix_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM fixes").fetchone()[0]


def set_plan(conn: sqlite3.Connection, geojson: str) -> None:
    conn.execute("INSERT OR REPLACE INTO plan (id, geojson) VALUES (1, ?)", (geojson,))
    conn.commit()


def get_plan(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT geojson FROM plan WHERE id = 1").fetchone()
    return row[0] if row else None


def clear_track(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM fixes")
    conn.commit()
