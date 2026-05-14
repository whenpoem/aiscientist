"""Shared cockpit database helpers.

Schema versions
---------------
v1 (initial): cockpit_interventions + cockpit_events.
v2 (v4.2.0a2 / ADR 0009): + cockpit_reports for the reports index. The
    table holds a row per generated report file under ``reports/`` so
    the Reports tab + detail-pane Reports section can index them
    without scanning the filesystem on every refresh.
v3: + cockpit_events created_at index for long-running sessions.
v4 (Phase E): + cockpit_events.source column carrying provenance
    (``memory_mcp`` / ``verify_mcp`` / ``prove_mcp`` / ``cockpit_mcp``
    / ``cockpit_user`` / ``cockpit_export``). Existing rows get
    ``NULL`` and the UI renders them as ``unknown``. The migration is
    additive — ``CREATE TABLE IF NOT EXISTS`` covers fresh installs;
    :func:`_ensure_event_source_column` runs ``ALTER TABLE`` for
    pre-v4 DBs.
"""

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
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  source TEXT
);

CREATE INDEX IF NOT EXISTS idx_cockpit_events_created_at
  ON cockpit_events(created_at);

CREATE TABLE IF NOT EXISTS cockpit_reports (
  report_id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK(kind IN
    ('closure', 'draft', 'diagnostic', 'portfolio', 'cascade')),
  related_node_id TEXT,
  format TEXT NOT NULL CHECK(format IN ('md', 'html')),
  bytes INTEGER NOT NULL DEFAULT 0,
  generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  generated_by TEXT NOT NULL DEFAULT 'unknown'
);

CREATE INDEX IF NOT EXISTS idx_cockpit_reports_node
  ON cockpit_reports(related_node_id);

CREATE INDEX IF NOT EXISTS idx_cockpit_reports_kind_time
  ON cockpit_reports(kind, generated_at DESC);
"""


def _ensure_event_source_column(con: sqlite3.Connection) -> None:
    """Idempotently add the ``source`` column to ``cockpit_events``.

    ``CREATE TABLE IF NOT EXISTS`` does not touch an existing table, so
    pre-v4 DBs still have the old 4-column schema after a plain run of
    :func:`apply_schema_migration`. This helper detects the missing
    column via ``PRAGMA table_info`` and runs the additive ``ALTER
    TABLE`` exactly once. Older code (pre-Phase-E) inserted without a
    source — those rows keep ``NULL`` and the cockpit's detail pane
    renders them as ``unknown``.
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(cockpit_events)")}
    if "source" in columns:
        return
    con.execute("ALTER TABLE cockpit_events ADD COLUMN source TEXT")
    con.commit()


def ensure() -> None:
    bootstrap_all()
    con = connect_sqlite(state_db_path())
    try:
        apply_schema_migration(con, "cockpit", COCKPIT_SCHEMA, schema_version=4)
        _ensure_event_source_column(con)
    finally:
        con.close()


def connect() -> sqlite3.Connection:
    ensure()
    return connect_sqlite(state_db_path())
