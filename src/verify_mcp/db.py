"""Shared database helpers for verify_mcp."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from claudescientist.runtime import (
    apply_schema_migration,
    cache_key,
    connect_sqlite,
    state_db_path,
)

VERIFY_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS ver_provenance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claim TEXT NOT NULL,
  value TEXT NOT NULL,
  session_id TEXT NOT NULL,
  source_command TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ver_provenance_claim ON ver_provenance(claim);
CREATE INDEX IF NOT EXISTS idx_ver_provenance_session ON ver_provenance(session_id);

CREATE TABLE IF NOT EXISTS ver_metric_pins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claim TEXT NOT NULL,
  value TEXT NOT NULL,
  provenance_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  source_command TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(provenance_id) REFERENCES ver_provenance(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ver_metric_pins_claim ON ver_metric_pins(claim);
CREATE INDEX IF NOT EXISTS idx_ver_metric_pins_session ON ver_metric_pins(session_id);
CREATE INDEX IF NOT EXISTS idx_ver_metric_pins_provenance ON ver_metric_pins(provenance_id);
"""

_BOOTSTRAPPED: set[str] = set()


def bootstrap() -> None:
    path = state_db_path()
    key = cache_key(path)
    if key in _BOOTSTRAPPED:
        return
    con = connect_sqlite(path)
    try:
        apply_schema_migration(con, "verify_mcp", VERIFY_SCHEMA)
    finally:
        con.close()
    _BOOTSTRAPPED.add(key)


def _connect() -> sqlite3.Connection:
    bootstrap()
    return connect_sqlite(state_db_path())


@contextmanager
def tx() -> sqlite3.Connection:
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
