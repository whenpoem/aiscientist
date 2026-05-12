"""Schema migration tests for prv_corpus_keywords (v4.2.0a0 / schema v5).

The v4 → v5 migration adds the ``embedding_model`` column with a
default of ``'unknown'``. This file verifies the migration runs on a
fresh DB (cheap — the column is just there), survives an explicit
v4-shaped DB rebuild (the legacy case), and never drops data.
"""

from __future__ import annotations


def test_fresh_db_has_embedding_model_column(workspace):
    db = workspace["prove_mcp.db"]
    con = db._connect()
    try:
        info = con.execute("PRAGMA table_info(prv_corpus_keywords)").fetchall()
    finally:
        con.close()
    column_names = {row["name"] for row in info}
    assert "embedding_model" in column_names


def test_migration_adds_column_to_legacy_table(workspace):
    """Simulate a v4.1 corpus by dropping the column, then re-bootstrap.

    On a freshly bootstrapped workspace the column already exists. We
    drop it (via the SQLite-compatible 'remove column' dance) to mimic
    a v4 DB, then call bootstrap again to confirm the migration helper
    re-adds it without touching existing keyword rows.
    """
    impl = workspace["prove_mcp.impl"]
    db = workspace["prove_mcp.db"]

    # Seed something so we can confirm the migration preserves rows.
    impl.ingest_proof_corpus(
        "manual",
        [
            {
                "problem_id": "legacy_p",
                "statement": "legacy row preservation test",
                "lexical_keywords": ["alpha"],
                "semantic_keywords": ["beta combo"],
            }
        ],
    )

    con = db._connect()
    try:
        # SQLite supports DROP COLUMN since 3.35 (Python 3.11 ships 3.35+),
        # but the column also feeds an index. We drop the index first so
        # the column drop has no dependents — exactly what a v4 DB looked
        # like before the v5 migration added either one.
        con.execute("DROP INDEX IF EXISTS idx_prv_corpus_keywords_model")
        con.execute("ALTER TABLE prv_corpus_keywords DROP COLUMN embedding_model")
        con.commit()
        info = con.execute("PRAGMA table_info(prv_corpus_keywords)").fetchall()
        assert all(row["name"] != "embedding_model" for row in info)
        legacy_rows = con.execute(
            "SELECT COUNT(*) AS n FROM prv_corpus_keywords"
        ).fetchone()["n"]
    finally:
        con.close()

    # Force a re-bootstrap so the migration helper runs against the
    # legacy-shaped table. We clear the module-level bootstrap cache to
    # make the second call do work.
    db._BOOTSTRAPPED.clear()
    db.bootstrap()

    con = db._connect()
    try:
        info = con.execute("PRAGMA table_info(prv_corpus_keywords)").fetchall()
        column_names = {row["name"] for row in info}
        assert "embedding_model" in column_names
        survived = con.execute(
            "SELECT COUNT(*) AS n FROM prv_corpus_keywords"
        ).fetchone()["n"]
        # Rows preserved by the ALTER TABLE ADD COLUMN path get the
        # default 'unknown' for the new column.
        default_rows = con.execute(
            "SELECT COUNT(*) AS n FROM prv_corpus_keywords "
            "WHERE embedding_model = 'unknown'"
        ).fetchone()["n"]
    finally:
        con.close()

    assert survived == legacy_rows
    assert default_rows == legacy_rows


def test_migration_is_idempotent(workspace):
    """Calling bootstrap repeatedly never duplicates the column or breaks."""
    db = workspace["prove_mcp.db"]
    for _ in range(3):
        db._BOOTSTRAPPED.clear()
        db.bootstrap()
    con = db._connect()
    try:
        info = con.execute("PRAGMA table_info(prv_corpus_keywords)").fetchall()
    finally:
        con.close()
    column_count = sum(1 for row in info if row["name"] == "embedding_model")
    assert column_count == 1
