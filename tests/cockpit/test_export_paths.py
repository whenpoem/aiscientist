from __future__ import annotations


def test_reports_dir_anchors_to_project_root_from_subdir(monkeypatch, tmp_path):
    from cockpit.export.paths import reports_dir

    repo = tmp_path / "repo"
    nested = repo / "docs"
    nested.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    monkeypatch.delenv("RESEARCH_AGENT_REPORTS_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(nested)

    assert reports_dir() == repo.resolve() / "reports"


def test_reports_dir_env_override_still_wins(monkeypatch, tmp_path):
    from cockpit.export.paths import reports_dir

    override = tmp_path / "custom-reports"
    monkeypatch.setenv("RESEARCH_AGENT_REPORTS_DIR", str(override))

    assert reports_dir() == override.resolve()
