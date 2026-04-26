"""Shared runtime helpers for paths, timestamps, and lightweight schema tracking."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path(".research-agent")
DEFAULT_DB_NAME = "state.db"
HELDOUT_DIR_ENV = "RESEARCH_AGENT_HELDOUT_DIR"
MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS ra_migrations (
  component TEXT PRIMARY KEY,
  schema_sha256 TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'applied',
  error TEXT NOT NULL DEFAULT '',
  applied_at TEXT NOT NULL
);
"""
COCKPIT_EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS cockpit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def state_db_path() -> Path:
    override = os.environ.get("RESEARCH_AGENT_DB_PATH")
    if override:
        return Path(override).expanduser()
    state_dir = os.environ.get("RESEARCH_AGENT_STATE_DIR")
    if state_dir:
        return Path(state_dir).expanduser() / DEFAULT_DB_NAME
    return DEFAULT_STATE_DIR / DEFAULT_DB_NAME


def runtime_path(*parts: str) -> Path:
    return state_db_path().parent.joinpath(*parts)


def heldout_root() -> Path:
    override = os.environ.get(HELDOUT_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".research-agent" / "heldout"


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cache_key(path: Path | None = None) -> str:
    return str((path or state_db_path()).resolve())


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_sqlite(path: Path | None = None, *, timeout: float = 5.0) -> sqlite3.Connection:
    target = ensure_parent(path or state_db_path())
    con = sqlite3.connect(str(target), timeout=timeout, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def ensure_columns(
    con: sqlite3.Connection,
    table_name: str,
    column_defs: dict[str, str],
) -> None:
    existing = {row["name"] for row in con.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for column_name, column_def in column_defs.items():
        if column_name not in existing:
            con.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def _ensure_migration_columns(con: sqlite3.Connection) -> None:
    ensure_columns(
        con,
        "ra_migrations",
        {
            "schema_version": "INTEGER NOT NULL DEFAULT 1",
            "status": "TEXT NOT NULL DEFAULT 'applied'",
            "error": "TEXT NOT NULL DEFAULT ''",
        },
    )


def apply_schema_migration(
    con: sqlite3.Connection,
    component: str,
    schema_text: str,
    *,
    schema_version: int = 1,
) -> None:
    con.executescript(MIGRATION_SCHEMA)
    _ensure_migration_columns(con)
    schema_hash = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
    row = con.execute(
        "SELECT schema_sha256, schema_version FROM ra_migrations WHERE component = ?",
        (component,),
    ).fetchone()
    if row is not None and row["schema_sha256"] != schema_hash:
        warnings.warn(
            (
                f"Schema hash changed for {component}; applying updated schema and "
                "refreshing the recorded hash."
            ),
            stacklevel=2,
        )
    con.execute(
        """
        INSERT INTO ra_migrations(
          component, schema_sha256, schema_version, status, error, applied_at
        )
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(component) DO UPDATE SET
          schema_sha256 = excluded.schema_sha256,
          schema_version = excluded.schema_version,
          status = excluded.status,
          error = excluded.error,
          applied_at = excluded.applied_at
        """,
        (component, schema_hash, schema_version, "applying", "", now_utc_iso()),
    )
    try:
        con.executescript(schema_text)
    except Exception as exc:
        con.execute(
            """
            UPDATE ra_migrations
            SET status = ?, error = ?, applied_at = ?
            WHERE component = ?
            """,
            ("failed", str(exc)[:500], now_utc_iso(), component),
        )
        raise
    con.execute(
        """
        INSERT INTO ra_migrations(
          component, schema_sha256, schema_version, status, error, applied_at
        )
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(component) DO UPDATE SET
          schema_sha256 = excluded.schema_sha256,
          schema_version = excluded.schema_version,
          status = excluded.status,
          error = excluded.error,
          applied_at = excluded.applied_at
        """,
        (component, schema_hash, schema_version, "applied", "", now_utc_iso()),
    )


def emit_cockpit_event(con: sqlite3.Connection, kind: str, payload: dict[str, Any]) -> int:
    con.execute(COCKPIT_EVENT_SCHEMA)
    cursor = con.execute(
        "INSERT INTO cockpit_events(kind, payload, created_at) VALUES(?,?,?)",
        (kind, json.dumps(payload, ensure_ascii=True), now_utc_iso()),
    )
    return int(cursor.lastrowid or 0)


def read_json_file(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data


def write_json_file(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
