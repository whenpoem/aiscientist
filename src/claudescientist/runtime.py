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
MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS ra_migrations (
  component TEXT PRIMARY KEY,
  schema_sha256 TEXT NOT NULL,
  applied_at TEXT NOT NULL
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


def apply_schema_migration(con: sqlite3.Connection, component: str, schema_text: str) -> None:
    con.executescript(MIGRATION_SCHEMA)
    schema_hash = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
    row = con.execute(
        "SELECT schema_sha256 FROM ra_migrations WHERE component = ?",
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
    con.executescript(schema_text)
    con.execute(
        """
        INSERT INTO ra_migrations(component, schema_sha256, applied_at)
        VALUES(?,?,?)
        ON CONFLICT(component) DO UPDATE SET
          schema_sha256 = excluded.schema_sha256,
          applied_at = excluded.applied_at
        """,
        (component, schema_hash, now_utc_iso()),
    )


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
