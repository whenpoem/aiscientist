"""Shared database helpers for verify_mcp."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(".research-agent/state.db")
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
"""

_BOOTSTRAPPED = False


def bootstrap() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
    try:
        con.row_factory = sqlite3.Row
        con.executescript(VERIFY_SCHEMA)
    finally:
        con.close()
    _BOOTSTRAPPED = True


def _connect() -> sqlite3.Connection:
    bootstrap()
    con = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


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

