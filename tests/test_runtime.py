from __future__ import annotations

import warnings

from claudescientist.runtime import apply_schema_migration, connect_sqlite


def test_apply_schema_migration_warns_when_schema_hash_changes(tmp_path):
    db_path = tmp_path / "state.db"

    con = connect_sqlite(db_path)
    try:
        apply_schema_migration(
            con,
            "demo",
            "CREATE TABLE IF NOT EXISTS demo_table(id INTEGER PRIMARY KEY);",
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            apply_schema_migration(
                con,
                "demo",
                "CREATE TABLE IF NOT EXISTS demo_table(id INTEGER PRIMARY KEY, name TEXT);",
            )
    finally:
        con.close()

    assert caught
    assert "Schema hash changed for demo" in str(caught[0].message)
