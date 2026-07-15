"""Migration test: v3.0 (schema_version=4) to current schema_version=6.

The v3.0 mem_nodes CHECK constraint did not include proof-trunk kinds,
and mem_failures had no ``domain`` column. v4.0 widens both. The
migration must:

1. Add the ``domain`` column to mem_failures with default ``'empirical'``
   (existing rows are tagged as empirical, which is the correct historical
   label).
2. Rebuild mem_nodes via the SQLite table-rebuild pattern so the widened
   CHECK takes effect, preserving every existing row and every foreign-key
   reference.

All migrations are idempotent; re-running bootstrap on a current
database is a no-op.

This test bypasses the standard ``workspace`` fixture because that fixture
calls ``cockpit.db.ensure()`` which triggers ``memory_mcp.db.bootstrap()``
immediately (jumping straight to the current schema). To exercise the migration path we
build the v3.0 schema by hand and then call bootstrap.
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest

V3_MEM_NODES_SCHEMA = """
CREATE TABLE mem_nodes (
  node_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN (
    'question', 'hypothesis', 'experiment', 'evidence', 'conclusion'
  )),
  text TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'active' CHECK(state IN (
    'active', 'refuted', 'superseded', 'archived'
  )),
  elo_score REAL NOT NULL DEFAULT 1500.0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT NOT NULL DEFAULT 'claude',
  parent_id TEXT REFERENCES mem_nodes(node_id)
);
"""

V3_MEM_FAILURES_SCHEMA = """
CREATE TABLE mem_failures (
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  symptom TEXT NOT NULL,
  root_cause TEXT DEFAULT '',
  resolution TEXT DEFAULT '',
  signature TEXT,
  seen_count INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _seed_v3_database(db_path: Path) -> None:
    """Build a minimal v3.0-shape state.db with one hypothesis and one failure."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(V3_MEM_NODES_SCHEMA)
        con.executescript(V3_MEM_FAILURES_SCHEMA)
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("hyp_v3legacy", "hypothesis", "v3.0-era hypothesis", "active", "claude"),
        )
        con.execute(
            """
            INSERT INTO mem_failures(trigger, symptom, root_cause, resolution)
            VALUES (?, ?, ?, ?)
            """,
            ("legacy oom", "cuda crash", "batch too big", "halve batch"),
        )
    finally:
        con.close()


@pytest.fixture
def migration_workspace(tmp_path, monkeypatch):
    """Like ``workspace`` but seeds a v3.0 DB and skips cockpit bootstrap."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_AGENT_STATE_DIR", str(tmp_path / ".research-agent"))
    db_path = tmp_path / ".research-agent" / "state.db"
    _seed_v3_database(db_path)
    module_names = [
        "memory_mcp.db",
        "memory_mcp.tools._common",
        "memory_mcp.tools.bt",
        "memory_mcp.tools.calibration",
        "memory_mcp.tools.failures",
        "memory_mcp.tools.graph",
        "memory_mcp.tools.literature",
        "memory_mcp.tools.replay",
        "memory_mcp.impl",
    ]
    loaded = {name: importlib.reload(importlib.import_module(name)) for name in module_names}
    return loaded, db_path


def test_v3_to_v5_migrates_failures_domain(migration_workspace):
    loaded, db_path = migration_workspace
    db_module = loaded["memory_mcp.db"]

    db_module.bootstrap()

    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        cols = [row[1] for row in con.execute("PRAGMA table_info(mem_failures)").fetchall()]
        assert "domain" in cols
        # Existing v3.0 row tagged as empirical by default.
        row = con.execute(
            "SELECT trigger, domain FROM mem_failures WHERE trigger = 'legacy oom'"
        ).fetchone()
        assert row[0] == "legacy oom"
        assert row[1] == "empirical"
    finally:
        con.close()


def test_v3_to_v5_widens_mem_nodes_kind_check(migration_workspace):
    loaded, db_path = migration_workspace
    db_module = loaded["memory_mcp.db"]

    db_module.bootstrap()

    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        # Pre-existing v3.0 row preserved verbatim.
        legacy = con.execute(
            "SELECT node_id, kind, text FROM mem_nodes WHERE node_id = 'hyp_v3legacy'"
        ).fetchone()
        assert legacy == ("hyp_v3legacy", "hypothesis", "v3.0-era hypothesis")
        # New proof-trunk kinds now insertable.
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("prop_post_migrate", "proposition", "post-migration proposition", "active", "test"),
        )
        kind = con.execute(
            "SELECT kind FROM mem_nodes WHERE node_id = 'prop_post_migrate'"
        ).fetchone()[0]
        assert kind == "proposition"
    finally:
        con.close()


def test_migration_is_idempotent(migration_workspace):
    loaded, db_path = migration_workspace
    db_module = loaded["memory_mcp.db"]

    db_module.bootstrap()
    # Second bootstrap on the same db must not crash and not re-rebuild the table.
    db_module._BOOTSTRAPPED.clear()  # force re-entry
    db_module.bootstrap()

    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        # Still has the legacy row, still has the new kind capability.
        legacy = con.execute(
            "SELECT kind FROM mem_nodes WHERE node_id = 'hyp_v3legacy'"
        ).fetchone()
        assert legacy[0] == "hypothesis"
        cols = [row[1] for row in con.execute("PRAGMA table_info(mem_failures)").fetchall()]
        assert "domain" in cols
    finally:
        con.close()


def test_v3_to_v5_preserves_foreign_key_integrity(migration_workspace):
    loaded, db_path = migration_workspace
    db_module = loaded["memory_mcp.db"]

    # Seed a parent-child link before migration.
    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by, parent_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("hyp_child", "hypothesis", "child hypothesis", "active", "claude", "hyp_v3legacy"),
        )
    finally:
        con.close()

    db_module.bootstrap()

    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        broken = con.execute("PRAGMA foreign_key_check").fetchall()
        assert broken == []
        parent = con.execute(
            "SELECT parent_id FROM mem_nodes WHERE node_id = 'hyp_child'"
        ).fetchone()
        assert parent[0] == "hyp_v3legacy"
    finally:
        con.close()


def test_current_migration_adds_bt_fit_state(migration_workspace):
    loaded, db_path = migration_workspace
    loaded["memory_mcp.db"].bootstrap()

    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        columns = {
            row[1] for row in con.execute("PRAGMA table_info(mem_bt_fit_state)")
        }
        migration = con.execute(
            "SELECT schema_version, status FROM ra_migrations "
            "WHERE component = 'memory_mcp'"
        ).fetchone()
    finally:
        con.close()

    assert {
        "kind",
        "node_order_json",
        "covariance_json",
        "comparison_count",
        "converged",
        "iterations",
        "fit_error",
        "fitted_at",
    } <= columns
    assert migration == (6, "applied")
