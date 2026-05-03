"""Shared cockpit database helpers."""

from __future__ import annotations

import sqlite3

from claudescientist.runtime import (
    apply_schema_migration,
    bootstrap_all,
    connect_sqlite,
    state_db_path,
)

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
    bootstrap_all()
    con = connect_sqlite(state_db_path())
    try:
        apply_schema_migration(con, "cockpit", COCKPIT_SCHEMA, schema_version=1)
    finally:
        con.close()


def connect() -> sqlite3.Connection:
    ensure()
    return connect_sqlite(state_db_path())
