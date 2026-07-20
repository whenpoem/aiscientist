from __future__ import annotations

import os
from pathlib import Path

from claudescientist import cli, doctor
from claudescientist.workspace_config import (
    configured_environment,
    read_workspace_config,
    write_workspace_config,
)


def _settings(tmp_path: Path) -> dict:
    return {
        "embedding": {
            "backend": "openai",
            "model": "custom-embedding",
            "base_url": "https://example.invalid/v1",
        },
        "heldout": {"directory": "private/heldout"},
        "research": {"auto_prune": True},
        "lean": {
            "enabled": True,
            "project_path": ".research-agent/lean/proofs",
        },
    }


def test_workspace_config_round_trip_and_relative_paths(tmp_path):
    path = write_workspace_config(_settings(tmp_path), tmp_path)
    loaded = read_workspace_config(tmp_path)

    assert path == tmp_path / ".research-agent" / "config.toml"
    assert loaded.errors == ()
    assert loaded.values["RESEARCH_AGENT_EMBED_BACKEND"] == "openai"
    assert loaded.values["RESEARCH_AGENT_AUTO_PRUNE"] == "1"
    assert loaded.values["RESEARCH_AGENT_HELDOUT_DIR"] == str(
        (tmp_path / "private" / "heldout").resolve()
    )
    assert loaded.values["LEAN_PROJECT_PATH"] == str(
        (tmp_path / ".research-agent" / "lean" / "proofs").resolve()
    )
    assert "API_KEY" not in path.read_text(encoding="utf-8")


def test_explicit_environment_wins_and_context_restores(tmp_path, monkeypatch):
    write_workspace_config(_settings(tmp_path), tmp_path)
    monkeypatch.setenv("RESEARCH_AGENT_EMBED_BACKEND", "mock")
    monkeypatch.delenv("RESEARCH_AGENT_AUTO_PRUNE", raising=False)

    with configured_environment(tmp_path):
        assert os.environ["RESEARCH_AGENT_EMBED_BACKEND"] == "mock"
        assert os.environ["RESEARCH_AGENT_AUTO_PRUNE"] == "1"

    assert os.environ["RESEARCH_AGENT_EMBED_BACKEND"] == "mock"
    assert "RESEARCH_AGENT_AUTO_PRUNE" not in os.environ


def test_invalid_workspace_config_is_reported(tmp_path):
    path = tmp_path / ".research-agent" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('[embedding]\nbackend = "unknown"\n', encoding="utf-8")

    loaded = read_workspace_config(tmp_path)
    assert loaded.exists is True
    assert "embedding.backend must be one of" in loaded.errors[0]


def test_configure_non_interactive_writes_normal_user_config(tmp_path, capsys):
    workspace = tmp_path / "research-project"
    assert (
        cli.main(
            [
                "configure",
                "--workspace",
                str(workspace),
                "--non-interactive",
                "--embedding-backend",
                "mock",
                "--heldout-dir",
                str(tmp_path / "heldout"),
                "--auto-prune",
                "--no-lean",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Workspace configured" in output
    loaded = read_workspace_config(workspace)
    assert loaded.values["RESEARCH_AGENT_EMBED_BACKEND"] == "mock"
    assert loaded.values["RESEARCH_AGENT_AUTO_PRUNE"] == "1"
    assert loaded.values["RESEARCH_AGENT_LEAN_ENABLED"] == "0"


def test_cli_loads_workspace_config_before_mcp_dispatch(tmp_path, monkeypatch):
    write_workspace_config(_settings(tmp_path), tmp_path)
    seen: dict[str, str | None] = {}

    def fake_run_mcp(server: str) -> int:
        seen["server"] = server
        seen["backend"] = os.environ.get("RESEARCH_AGENT_EMBED_BACKEND")
        seen["auto_prune"] = os.environ.get("RESEARCH_AGENT_AUTO_PRUNE")
        return 0

    monkeypatch.delenv("RESEARCH_AGENT_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("RESEARCH_AGENT_AUTO_PRUNE", raising=False)
    monkeypatch.setattr(cli, "_run_mcp", fake_run_mcp)

    assert cli.main(["mcp", "memory", "--workspace", str(tmp_path)]) == 0
    assert seen == {"server": "memory", "backend": "openai", "auto_prune": "1"}
    assert "RESEARCH_AGENT_AUTO_PRUNE" not in os.environ


def test_lean_mcp_uses_workspace_project_path(tmp_path, monkeypatch):
    project = tmp_path / ".research-agent" / "lean" / "proofs"
    project.mkdir(parents=True)
    (project / "lakefile.lean").write_text("import Mathlib\n", encoding="utf-8")
    settings = _settings(tmp_path)
    settings["lean"]["project_path"] = str(project)
    write_workspace_config(settings, tmp_path)
    commands: list[list[str]] = []

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "uv")
    monkeypatch.setattr(
        cli.subprocess,
        "call",
        lambda command: (commands.append(list(command)), 0)[1],
    )

    assert cli.main(["mcp", "lean", "--workspace", str(tmp_path)]) == 0
    assert commands == [
        [
            "uv",
            "tool",
            "run",
            "lean-lsp-mcp",
            "--lean-project-path",
            str(project),
        ]
    ]


def test_doctor_loads_workspace_configuration(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings["embedding"] = {"backend": "mock", "model": "mock", "base_url": ""}
    settings["lean"]["enabled"] = False
    write_workspace_config(settings, tmp_path)
    monkeypatch.delenv("RESEARCH_AGENT_EMBED_BACKEND", raising=False)
    monkeypatch.setattr(
        doctor,
        "_codex_plugin_status",
        lambda: {"available": True, "installed": True, "enabled": True},
    )
    monkeypatch.setattr(doctor, "_trusted_claudescientist_hooks", lambda: True)

    checks = doctor.run_doctor(tmp_path)["checks"]
    assert checks["workspace_configuration"]["status"] == "ok"
    assert checks["embedding_backend"]["backend"] == "mock"
    assert checks["embedding_backend"]["status"] == "ok"
