"""Shared cockpit database helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from memory_mcp.db import bootstrap as bootstrap_memory
from verify_mcp.db import bootstrap as bootstrap_verify

DB = Path(".research-agent/state.db")
COCKPIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS cockpit_interventions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  target TEXT,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS cockpit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure() -> None:
    bootstrap_memory()
    bootstrap_verify()
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB), timeout=5.0, isolation_level=None)
    try:
        con.row_factory = sqlite3.Row
        con.executescript(COCKPIT_SCHEMA)
    finally:
        con.close()


def connect() -> sqlite3.Connection:
    ensure()
    con = sqlite3.connect(str(DB), timeout=5.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con

