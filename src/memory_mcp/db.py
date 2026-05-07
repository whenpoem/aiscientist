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

# v5 widens mem_nodes.kind CHECK to include proof-trunk kinds and adds
# mem_failures.domain. ADR 0008 + architecture.md §13.
_PROOF_KINDS = ("proposition", "proof_skeleton", "proof_snippet")


def _ensure_elo_column(con: sqlite3.Connection) -> None:
    ensure_columns(con, "mem_nodes", {"elo_score": "REAL NOT NULL DEFAULT 1500.0"})


def _ensure_failures_domain(con: sqlite3.Connection) -> None:
    """Backfill mem_failures.domain for v3.x → v4.0 databases.

    ALTER TABLE ADD COLUMN populates existing rows with the default
    ('empirical'), which is the correct historical label since every
    pre-v4.0 failure record came from the empirical trunk.
    """
    ensure_columns(
        con,
        "mem_failures",
        {"domain": "TEXT NOT NULL DEFAULT 'empirical'"},
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_mem_failures_domain ON mem_failures(domain)"
    )


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


def _migrate_kind_check(con: sqlite3.Connection) -> None:
    """Widen mem_nodes.kind CHECK to include proof-trunk kinds (v5).

    SQLite cannot alter a CHECK constraint in place. For v3.x → v4.0
    databases we rebuild mem_nodes following the official table-rebuild
    pattern (https://sqlite.org/lang_altertable.html). The rebuild is
    a no-op when the constraint already includes 'proposition'.

    Foreign keys are temporarily disabled, the new table is created with
    the widened CHECK, rows are copied verbatim, the old table is
    dropped, the new table is renamed into place, and PRAGMA
    foreign_key_check verifies referential integrity before commit.
    """
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='mem_nodes'"
    ).fetchone()
    if not row or not row["sql"]:
        return
    if "proposition" in row["sql"]:
        return  # already widened

    if con.in_transaction:
        con.commit()

    # SQLite requires foreign_keys OFF for a safe table rebuild.
    # If mem_nodes ever gains indexes or triggers, recreate them here
    # after ALTER TABLE ... RENAME; DROP TABLE removes attached objects.
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """
            CREATE TABLE mem_nodes_new (
              node_id TEXT PRIMARY KEY,
              kind TEXT NOT NULL CHECK(kind IN (
                'question', 'hypothesis', 'experiment', 'evidence', 'conclusion',
                'proposition', 'proof_skeleton', 'proof_snippet'
              )),
              text TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'active'
                CHECK(state IN ('active', 'refuted', 'superseded', 'archived')),
              elo_score REAL NOT NULL DEFAULT 1500.0,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by TEXT NOT NULL DEFAULT 'claude',
              parent_id TEXT REFERENCES mem_nodes(node_id)
            )
            """
        )
        con.execute(
            """
            INSERT INTO mem_nodes_new(
              node_id, kind, text, state, elo_score,
              created_at, created_by, parent_id
            )
            SELECT node_id, kind, text, state, elo_score,
                   created_at, created_by, parent_id
            FROM mem_nodes
            """
        )
        con.execute("DROP TABLE mem_nodes")
        con.execute("ALTER TABLE mem_nodes_new RENAME TO mem_nodes")
        broken = con.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            con.execute("ROLLBACK")
            raise RuntimeError(
                f"foreign_key_check failed after mem_nodes rebuild: {list(broken)}"
            )
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")


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
            schema_version=5,
        )
        _ensure_elo_column(con)
        _ensure_failures_domain(con)
        _migrate_kind_check(con)
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
