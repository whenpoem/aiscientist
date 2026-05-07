"""Shared database helpers for prove_mcp (P2)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from claudescientist.runtime import (
    apply_schema_migration,
    cache_key,
    connect_sqlite,
    state_db_path,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_BOOTSTRAPPED: set[str] = set()


def bootstrap() -> None:
    path = state_db_path()
    key = cache_key(path)
    if key in _BOOTSTRAPPED:
        return
    con = connect_sqlite(path)
    try:
        apply_schema_migration(
            con,
            "prove_mcp",
            SCHEMA_PATH.read_text(encoding="utf-8"),
            schema_version=3,
        )
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
