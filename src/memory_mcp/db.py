"""Shared database helpers for memory_mcp."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from claudescientist.runtime import (
    apply_schema_migration,
    cache_key,
    connect_sqlite,
    ensure_columns,
    state_db_path,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_BOOTSTRAPPED: set[str] = set()


def _ensure_elo_column(con: sqlite3.Connection) -> None:
    ensure_columns(con, "mem_nodes", {"elo_score": "REAL NOT NULL DEFAULT 1500.0"})


def _ensure_bt_seeded(con: sqlite3.Connection) -> None:
    """Backfill mem_bt_ratings rows for any existing hypothesis nodes."""
    con.execute(
        """
        INSERT INTO mem_bt_ratings (node_id)
        SELECT node_id FROM mem_nodes
        WHERE kind = 'hypothesis'
          AND node_id NOT IN (SELECT node_id FROM mem_bt_ratings)
        """
    )


def bootstrap() -> None:
    path = state_db_path()
    key = cache_key(path)
    if key in _BOOTSTRAPPED:
        return
    con = connect_sqlite(path)
    try:
        apply_schema_migration(
            con,
            "memory_mcp",
            SCHEMA_PATH.read_text(encoding="utf-8"),
            schema_version=4,
        )
        _ensure_elo_column(con)
        _ensure_bt_seeded(con)
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
