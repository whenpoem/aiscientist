"""Shared database helpers for prove_mcp.

Schema version history
----------------------
v1: initial corpus + keywords (P2).
v2: + diagnostic manifests (P3).
v3: + lean attempts (P4).
v4: widen prv_lean_attempts.triage_difficulty CHECK to include 'n/a' so
    rejected propositions are distinguishable from eligible-but-hard ones
    (Plan v2 / Bug D fix). The migration is a SQLite table rebuild because
    CHECK constraints can't be altered in place.
v5: + prv_corpus_keywords.embedding_model column (v4.2.0a0 / ADR 0010).
    Lets the corpus distinguish keyword rows produced by different models
    under the same backend (e.g. several OpenAI-compatible providers, or
    an upgrade from all-MiniLM-L6-v2 to Qwen3-Embedding-0.6B under the
    local backend). ALTER TABLE ADD COLUMN is enough — no rebuild needed.
"""

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


def _migrate_lean_attempts_difficulty_check(con: sqlite3.Connection) -> None:
    """Widen prv_lean_attempts.triage_difficulty CHECK to include 'n/a' (v4).

    SQLite cannot alter a CHECK constraint in place. For v3 -> v4
    databases we rebuild the table using the official rebuild pattern.
    No-op once the constraint already lists 'n/a'.
    """
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='prv_lean_attempts'"
    ).fetchone()
    if not row or not row["sql"]:
        return
    if "'n/a'" in row["sql"]:
        return  # already widened

    if con.in_transaction:
        con.commit()

    con.execute("PRAGMA foreign_keys=OFF")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """
            CREATE TABLE prv_lean_attempts_new (
              attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
              proposition_id TEXT NOT NULL,
              status TEXT NOT NULL
                CHECK(status IN ('queued', 'running', 'verified', 'failed', 'timeout')),
              lean_source TEXT NOT NULL DEFAULT '',
              stderr TEXT NOT NULL DEFAULT '',
              duration_sec REAL,
              triage_eligible INTEGER NOT NULL DEFAULT 0
                CHECK(triage_eligible IN (0, 1)),
              triage_reasons TEXT NOT NULL DEFAULT '[]',
              triage_difficulty TEXT NOT NULL DEFAULT 'unknown'
                CHECK(triage_difficulty IN ('low', 'med', 'high', 'n/a', 'unknown')),
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        con.execute(
            """
            INSERT INTO prv_lean_attempts_new(
              attempt_id, proposition_id, status, lean_source, stderr,
              duration_sec, triage_eligible, triage_reasons, triage_difficulty,
              created_at
            )
            SELECT attempt_id, proposition_id, status, lean_source, stderr,
                   duration_sec, triage_eligible, triage_reasons, triage_difficulty,
                   created_at
            FROM prv_lean_attempts
            """
        )
        con.execute("DROP TABLE prv_lean_attempts")
        con.execute("ALTER TABLE prv_lean_attempts_new RENAME TO prv_lean_attempts")
        # Recreate indexes; they were dropped with the old table.
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_prv_lean_attempts_proposition "
            "ON prv_lean_attempts(proposition_id)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_prv_lean_attempts_status "
            "ON prv_lean_attempts(status)"
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


def _migrate_add_embedding_model_column(con: sqlite3.Connection) -> None:
    """Add prv_corpus_keywords.embedding_model on v4 → v5 upgrade.

    SQLite allows ALTER TABLE ADD COLUMN with a default, so this
    migration stays lightweight: existing rows pick up the default
    'unknown' value, and ``retrieve_skeletons`` surfaces a clean hint
    when it encounters those rows under a newly-pinned model. The
    sibling index makes the (backend, model, dim) filter cheap. No-op
    once the column already exists.
    """
    ensure_columns(
        con,
        "prv_corpus_keywords",
        {"embedding_model": "TEXT NOT NULL DEFAULT 'unknown'"},
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_prv_corpus_keywords_model "
        "ON prv_corpus_keywords(embed_backend, embedding_model, embed_dim)"
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
            "prove_mcp",
            SCHEMA_PATH.read_text(encoding="utf-8"),
            schema_version=5,
        )
        _migrate_lean_attempts_difficulty_check(con)
        _migrate_add_embedding_model_column(con)
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
