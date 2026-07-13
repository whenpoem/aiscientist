"""Shared database helpers for verify_mcp."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from claudescientist.runtime import (
    apply_schema_migration,
    cache_key,
    connect_sqlite,
    ensure_columns,
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

CREATE TABLE IF NOT EXISTS ver_seed_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  script_path TEXT NOT NULL,
  seed_arg TEXT NOT NULL DEFAULT '--seed',
  seeds_json TEXT NOT NULL,
  metric_pattern TEXT NOT NULL,
  values_json TEXT NOT NULL,
  mean_value REAL NOT NULL,
  std_value REAL NOT NULL,
  verdict TEXT NOT NULL,
  metric_pin_id INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ver_seed_runs_metric_pin ON ver_seed_runs(metric_pin_id);

CREATE TABLE IF NOT EXISTS ver_heldout_budgets (
  dataset TEXT PRIMARY KEY,
  heldout_path TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  budget_total INTEGER NOT NULL DEFAULT 5,
  budget_used INTEGER NOT NULL DEFAULT 0,
  registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ver_heldout_queries (
  query_id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset TEXT NOT NULL,
  model_path TEXT NOT NULL,
  batch_size INTEGER NOT NULL DEFAULT 1,
  metric_value REAL,
  status TEXT NOT NULL DEFAULT 'completed',
  error TEXT NOT NULL DEFAULT '',
  completed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(dataset) REFERENCES ver_heldout_budgets(dataset) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ver_heldout_queries_dataset ON ver_heldout_queries(dataset);

CREATE TABLE IF NOT EXISTS ver_provenance_dag (
  prov_id INTEGER PRIMARY KEY REFERENCES ver_provenance(id) ON DELETE CASCADE,
  input_hashes TEXT NOT NULL DEFAULT '[]',
  output_hash TEXT NOT NULL DEFAULT '',
  parent_prov_ids TEXT NOT NULL DEFAULT '[]',
  stale INTEGER NOT NULL DEFAULT 0,
  refreshed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ver_provenance_dag_stale
  ON ver_provenance_dag(stale);

CREATE TABLE IF NOT EXISTS ver_preregistrations (
  prereg_id TEXT PRIMARY KEY,
  hypothesis_id TEXT,
  metric_name TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('higher_better', 'lower_better')),
  threshold REAL,
  heldout_dataset TEXT,
  seed_count INTEGER NOT NULL DEFAULT 5,
  alpha REAL NOT NULL DEFAULT 0.05,
  mc_correction TEXT NOT NULL DEFAULT 'bonferroni'
    CHECK(mc_correction IN ('bh', 'bonferroni', 'none')),
  family_id TEXT NOT NULL DEFAULT '',
  family_size INTEGER NOT NULL DEFAULT 1 CHECK(family_size > 0),
  observed_value REAL,
  observed_p_value REAL,
  adjusted_p_value REAL,
  resolution_note TEXT NOT NULL DEFAULT '',
  locked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open', 'met', 'missed', 'withdrawn'))
);

CREATE INDEX IF NOT EXISTS idx_ver_preregistrations_hypothesis
  ON ver_preregistrations(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_ver_preregistrations_status
  ON ver_preregistrations(status);

CREATE TABLE IF NOT EXISTS ver_run_manifests (
  manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
  provenance_id INTEGER REFERENCES ver_provenance(id) ON DELETE CASCADE,
  seed_run_id INTEGER REFERENCES ver_seed_runs(run_id) ON DELETE CASCADE,
  manifest_json TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(provenance_id IS NOT NULL OR seed_run_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_ver_run_manifests_provenance
  ON ver_run_manifests(provenance_id);
CREATE INDEX IF NOT EXISTS idx_ver_run_manifests_seed_run
  ON ver_run_manifests(seed_run_id);

CREATE TABLE IF NOT EXISTS res_budget_ledger (
  budget_id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL,
  resource TEXT NOT NULL CHECK(resource IN
    ('wallclock_sec', 'llm_tokens', 'heldout_queries', 'disk_mb')),
  limit_value REAL NOT NULL,
  used_value REAL NOT NULL DEFAULT 0,
  window TEXT NOT NULL DEFAULT 'session',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(scope, resource, window)
);

CREATE INDEX IF NOT EXISTS idx_res_budget_scope_resource
  ON res_budget_ledger(scope, resource);
"""

_BOOTSTRAPPED: set[str] = set()


def _ensure_heldout_query_columns(con: sqlite3.Connection) -> None:
    ensure_columns(
        con,
        "ver_heldout_queries",
        {
            "status": "TEXT NOT NULL DEFAULT 'completed'",
            "error": "TEXT NOT NULL DEFAULT ''",
            "completed_at": "TEXT",
        },
    )


def _ensure_preregistration_family_columns(con: sqlite3.Connection) -> None:
    """Add fixed-family metadata and conservatively backfill legacy rows."""
    ensure_columns(
        con,
        "ver_preregistrations",
        {
            "family_id": "TEXT NOT NULL DEFAULT ''",
            "family_size": "INTEGER NOT NULL DEFAULT 1",
        },
    )
    open_count = int(
        con.execute(
            """
            SELECT COUNT(*) FROM ver_preregistrations
            WHERE status = 'open' AND family_id = ''
            """
        ).fetchone()[0]
    )
    if open_count:
        con.execute(
            """
            UPDATE ver_preregistrations
            SET family_id = 'legacy_open_v5', family_size = ?
            WHERE status = 'open' AND family_id = ''
            """,
            (open_count,),
        )
    con.execute(
        """
        UPDATE ver_preregistrations
        SET family_id = 'legacy_' || prereg_id, family_size = 1
        WHERE family_id = ''
        """
    )


def bootstrap() -> None:
    path = state_db_path()
    key = cache_key(path)
    if key in _BOOTSTRAPPED:
        return
    con = connect_sqlite(path)
    try:
        apply_schema_migration(con, "verify_mcp", VERIFY_SCHEMA, schema_version=5)
        _ensure_heldout_query_columns(con)
        _ensure_preregistration_family_columns(con)
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
