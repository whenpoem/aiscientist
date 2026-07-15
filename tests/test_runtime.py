from __future__ import annotations

import warnings

import pytest

from claudescientist.runtime import (
    apply_schema_migration,
    begin_immediate_with_retry,
    connect_existing_sqlite,
    connect_sqlite,
    installation_root,
    project_root,
    state_db_path,
    workspace_root,
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


def test_project_root_prefers_claude_project_dir(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "docs" / "adr"
    nested.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))

    assert project_root() == repo.resolve()


def test_project_root_walks_up_when_env_missing(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "docs" / "adr"
    nested.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(nested)

    assert project_root() == repo.resolve()


def test_state_db_path_anchors_to_project_root_from_subdir(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "docs"
    nested.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    monkeypatch.delenv("RESEARCH_AGENT_DB_PATH", raising=False)
    monkeypatch.delenv("RESEARCH_AGENT_STATE_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(nested)

    assert state_db_path() == repo.resolve() / ".research-agent" / "state.db"


def test_state_db_env_overrides_still_win(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    override = tmp_path / "custom" / "state.db"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setenv("RESEARCH_AGENT_DB_PATH", str(override))

    assert state_db_path() == override


def test_workspace_root_accepts_external_research_project(monkeypatch, tmp_path):
    research_project = tmp_path / "external-research"
    research_project.mkdir()
    (research_project / "README.md").write_text("research\n", encoding="utf-8")
    monkeypatch.delenv("RESEARCH_AGENT_WORKSPACE", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(research_project))
    monkeypatch.delenv("RESEARCH_AGENT_DB_PATH", raising=False)
    monkeypatch.delenv("RESEARCH_AGENT_STATE_DIR", raising=False)

    assert project_root(start=research_project) is None
    assert workspace_root() == research_project.resolve()
    assert state_db_path() == research_project.resolve() / ".research-agent" / "state.db"


def test_explicit_workspace_override_wins_over_host_directory(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit"
    host = tmp_path / "host"
    explicit.mkdir()
    host.mkdir()
    monkeypatch.setenv("RESEARCH_AGENT_WORKSPACE", str(explicit))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(host))

    assert workspace_root() == explicit.resolve()


def test_documented_workspace_root_override_precedes_legacy_alias(monkeypatch, tmp_path):
    documented = tmp_path / "documented"
    legacy = tmp_path / "legacy"
    documented.mkdir()
    legacy.mkdir()
    monkeypatch.setenv("RESEARCH_AGENT_WORKSPACE_ROOT", str(documented))
    monkeypatch.setenv("RESEARCH_AGENT_WORKSPACE", str(legacy))

    assert workspace_root() == documented.resolve()


def test_begin_immediate_retries_only_lock_contention(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.calls = 0

        def execute(self, _statement):
            self.calls += 1
            if self.calls < 3:
                raise __import__("sqlite3").OperationalError("database is locked")

    connection = FakeConnection()
    monkeypatch.setattr("claudescientist.runtime.time.sleep", lambda _delay: None)
    monkeypatch.setattr("claudescientist.runtime.random.uniform", lambda _a, _b: 0.0)

    begin_immediate_with_retry(connection)  # type: ignore[arg-type]

    assert connection.calls == 3


def test_installation_root_is_independent_from_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_AGENT_WORKSPACE", str(tmp_path))
    installed = installation_root()
    assert installed != tmp_path.resolve()
    assert installed.exists()
