"""Shared runtime helpers for paths, timestamps, and lightweight schema tracking."""

from __future__ import annotations

import hashlib
import json
import os
import re
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


def connect_existing_sqlite(
    path: Path | None = None,
    *,
    timeout: float = 2.0,
) -> sqlite3.Connection | None:
    """Open an existing state DB without creating it.

    Short-lived hooks use this helper so first-run or malformed workspaces
    still fail open: a missing DB means "nothing to read", not "create an
    empty runtime DB during a lifecycle hook".
    """
    target = path or state_db_path()
    if not target.exists():
        return None
    con = sqlite3.connect(str(target), timeout=timeout, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
    except sqlite3.DatabaseError:
        con.close()
        return None
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


# ---------------------------------------------------------------------------
# Numeric-claim recognition (project-wide).
#
# These constants describe how the project recognises a numeric claim in any
# textual stream (script stdout, commit message, manuscript paragraph). They
# live in runtime because both verify_mcp.provenance and the leakage /
# provenance hooks need them; keeping them in any single business module would
# force the others to reach across layers.
# ---------------------------------------------------------------------------

METRIC_RE = re.compile(
    r"(?P<label>(?:acc(?:uracy)?|f1|auc|loss|precision|recall|mse|rmse|mae|bleu|rouge|score|metric)[^:=\n]{0,24})"
    r"[:= ]+"
    r"(?P<value>[-+]?\d+(?:\.\d+)?%?)",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?%?")


def extract_metric_tokens(text: str) -> list[str]:
    """Return labelled numeric values found in ``text``; fall back to bare numbers."""
    values = [match.group("value") for match in METRIC_RE.finditer(text)]
    if values:
        return values
    return NUMBER_RE.findall(text)


# ---------------------------------------------------------------------------
# Component bootstrap registry.
#
# Modules that own SQLite schemas register themselves implicitly through the
# ``KNOWN_BOOTSTRAP_COMPONENTS`` tuple. Cockpit and other entry points call
# ``bootstrap_all()`` to ensure every known schema is ready before reading.
# Adding a new MCP server in the future means appending its bootstrap module
# here — and only here.
# ---------------------------------------------------------------------------

KNOWN_BOOTSTRAP_COMPONENTS: tuple[str, ...] = (
    "memory_mcp.db",
    "verify_mcp.db",
    "prove_mcp.db",
)


def bootstrap_all() -> None:
    """Trigger bootstrap on every component registered in ``KNOWN_BOOTSTRAP_COMPONENTS``.

    Each named module must expose a module-level ``bootstrap()`` function that
    is idempotent. Called by the cockpit before it reads cross-component
    tables; safe to invoke multiple times per process.
    """
    from importlib import import_module

    for module_name in KNOWN_BOOTSTRAP_COMPONENTS:
        module = import_module(module_name)
        module.bootstrap()
