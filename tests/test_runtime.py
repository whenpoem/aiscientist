from __future__ import annotations

import warnings

import pytest

from claudescientist.runtime import (
    apply_schema_migration,
    connect_existing_sqlite,
    connect_sqlite,
)


def test_apply_schema_migration_warns_when_schema_hash_changes(tmp_path):
    db_path = tmp_path / "state.db"

    con = connect_sqlite(db_path)
    try:
        apply_schema_migration(
            con,
            "demo",
            "CREATE TABLE IF NOT EXISTS demo_table(id INTEGER PRIMARY KEY);",
            schema_version=1,
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            apply_schema_migration(
                con,
                "demo",
                "CREATE TABLE IF NOT EXISTS demo_table(id INTEGER PRIMARY KEY, name TEXT);",
                schema_version=2,
            )
        row = con.execute(
            """
            SELECT schema_version, status, error
            FROM ra_migrations
            WHERE component = ?
            """,
            ("demo",),
        ).fetchone()
    finally:
        con.close()

    assert caught
    assert "Schema hash changed for demo" in str(caught[0].message)
    assert row["schema_version"] == 2
    assert row["status"] == "applied"
    assert row["error"] == ""


def test_apply_schema_migration_records_failure_status(tmp_path):
    db_path = tmp_path / "state.db"

    con = connect_sqlite(db_path)
    try:
        with pytest.raises(Exception):
            apply_schema_migration(
                con,
                "broken",
                "CREATE TABLE broken(",
                schema_version=7,
            )
        row = con.execute(
            """
            SELECT schema_version, status, error
            FROM ra_migrations
            WHERE component = ?
            """,
            ("broken",),
        ).fetchone()
    finally:
        con.close()

    assert row["schema_version"] == 7
    assert row["status"] == "failed"
    assert row["error"]


def test_connect_existing_sqlite_does_not_create_missing_db(tmp_path):
    db_path = tmp_path / "missing" / "state.db"

    con = connect_existing_sqlite(db_path)

    assert con is None
    assert not db_path.exists()


def test_connect_existing_sqlite_returns_none_for_unopenable_existing_path(tmp_path):
    db_path = tmp_path / "state.db"
    db_path.mkdir()

    con = connect_existing_sqlite(db_path)

    assert con is None
    assert db_path.is_dir()


def test_connect_existing_sqlite_uses_runtime_pragmas(tmp_path):
    db_path = tmp_path / "state.db"
    created = connect_sqlite(db_path)
    created.close()

    con = connect_existing_sqlite(db_path)
    try:
        assert con is not None
        assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert con.row_factory is not None
    finally:
        if con is not None:
            con.close()
