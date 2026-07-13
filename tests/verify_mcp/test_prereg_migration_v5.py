"""Migration coverage for fixed preregistration families in verify schema v5."""

from __future__ import annotations

import importlib
import sqlite3

LEGACY_PREREG_SCHEMA = """
CREATE TABLE ver_preregistrations (
  prereg_id TEXT PRIMARY KEY,
  hypothesis_id TEXT,
  metric_name TEXT NOT NULL,
  direction TEXT NOT NULL,
  threshold REAL,
  heldout_dataset TEXT,
  seed_count INTEGER NOT NULL DEFAULT 5,
  alpha REAL NOT NULL DEFAULT 0.05,
  mc_correction TEXT NOT NULL DEFAULT 'bonferroni',
  observed_value REAL,
  observed_p_value REAL,
  adjusted_p_value REAL,
  resolution_note TEXT NOT NULL DEFAULT '',
  locked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT,
  status TEXT NOT NULL DEFAULT 'open'
);
"""


def test_legacy_open_rows_receive_one_conservative_fixed_family(tmp_path, monkeypatch):
    state_dir = tmp_path / ".research-agent"
    db_path = state_dir / "state.db"
    state_dir.mkdir()
    con = sqlite3.connect(db_path, isolation_level=None)
    try:
        con.executescript(LEGACY_PREREG_SCHEMA)
        con.executemany(
            """
            INSERT INTO ver_preregistrations(
              prereg_id, metric_name, direction, status
            ) VALUES(?, ?, 'higher_better', ?)
            """,
            [
                ("prereg_open_a", "acc_a", "open"),
                ("prereg_open_b", "acc_b", "open"),
                ("prereg_done", "acc_done", "met"),
            ],
        )
    finally:
        con.close()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_AGENT_STATE_DIR", str(state_dir))
    db = importlib.reload(importlib.import_module("verify_mcp.db"))
    db.bootstrap()

    con = sqlite3.connect(db_path)
    try:
        open_rows = con.execute(
            """
            SELECT family_id, family_size
            FROM ver_preregistrations
            WHERE status = 'open'
            ORDER BY prereg_id
            """
        ).fetchall()
        resolved = con.execute(
            """
            SELECT family_id, family_size
            FROM ver_preregistrations
            WHERE prereg_id = 'prereg_done'
            """
        ).fetchone()
        schema_version = con.execute(
            "SELECT schema_version FROM ra_migrations WHERE component = 'verify_mcp'"
        ).fetchone()[0]
    finally:
        con.close()

    assert open_rows == [("legacy_open_v5", 2), ("legacy_open_v5", 2)]
    assert resolved == ("legacy_prereg_done", 1)
    assert schema_version == 5

    db._BOOTSTRAPPED.clear()
    db.bootstrap()
    con = sqlite3.connect(db_path)
    try:
        after_second_bootstrap = con.execute(
            """
            SELECT family_id, family_size
            FROM ver_preregistrations
            WHERE status = 'open'
            ORDER BY prereg_id
            """
        ).fetchall()
    finally:
        con.close()
    assert after_second_bootstrap == open_rows
