from __future__ import annotations

import io
import json
import sys
import tomllib
from pathlib import Path

from claudescientist import cli, codex_hooks

ROOT = Path(__file__).resolve().parents[2]


def test_plugin_manifest_and_python_package_versions_match() -> None:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert manifest["name"] == project["project"]["name"] == "claudescientist"
    assert manifest["version"] == project["project"]["version"] == "5.1.0"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert (ROOT / "hooks" / "hooks.json").is_file()


def test_public_marketplace_points_to_repository_root_plugin() -> None:
    marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    assert marketplace["name"] == "claudescientist"
    entries = marketplace["plugins"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["name"] == "claudescientist"
    assert entry["source"] == {
        "source": "url",
        "url": "https://github.com/whenpoem/aiscientist.git",
    }
    assert entry["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }


def test_plugin_enables_only_version_pinned_core_mcps() -> None:
    config = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert set(config) == {"memory", "verify", "prove", "cockpit"}
    for name, server in config.items():
        assert server["command"] == "uv"
        assert "claudescientist==5.1.0" in server["args"]
        assert server["args"][-2:] == ["mcp", name]


def test_plugin_hooks_are_version_pinned_and_include_intervention_bridge() -> None:
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    commands = [
        hook["command"]
        for groups in hooks.values()
        for group in groups
        for hook in group["hooks"]
    ]
    assert commands
    assert all("claudescientist==5.1.0" in command for command in commands)
    assert any("intervention_pump" in command for command in commands)


def test_plugin_and_project_skill_surfaces_are_byte_identical() -> None:
    source = ROOT / ".claude" / "skills"
    for source_file in source.rglob("*"):
        if not source_file.is_file():
            continue
        relative = source_file.relative_to(source)
        assert (ROOT / ".agents" / "skills" / relative).read_bytes() == source_file.read_bytes()
        assert (ROOT / "skills" / relative).read_bytes() == source_file.read_bytes()


def test_plugin_root_resolves_hooks_outside_source_checkout(tmp_path, monkeypatch):
    plugin = tmp_path / "installed-plugin"
    hook = plugin / ".claude" / "hooks" / "stop_flush.py"
    hook.parent.mkdir(parents=True)
    hook.write_text("print('{}')\n", encoding="utf-8")
    monkeypatch.setenv("PLUGIN_ROOT", str(plugin))
    assert codex_hooks._hook_path("stop_flush") == hook  # noqa: SLF001


def test_external_workspace_cockpit_and_plugin_hook_share_one_database(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "external-research"
    workspace.mkdir()
    monkeypatch.setenv("RESEARCH_AGENT_WORKSPACE", str(workspace))
    monkeypatch.setenv("PLUGIN_ROOT", str(ROOT))
    monkeypatch.delenv("RESEARCH_AGENT_DB_PATH", raising=False)
    monkeypatch.delenv("RESEARCH_AGENT_STATE_DIR", raising=False)

    from cockpit import data

    queued = data.write_intervention("halt", None, "pause before the next experiment")
    assert queued["intervention_id"] > 0

    stdin = io.StringIO(
        json.dumps({"hookEventName": "UserPromptSubmit", "session_id": "plugin-e2e"})
    )
    original_stdout = sys.stdout
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert codex_hooks.main(["intervention_pump", "--event", "UserPromptSubmit"]) == 0
    delivered = json.loads(stdout.getvalue())
    assert "pause before the next experiment" in delivered["hookSpecificOutput"][
        "additionalContext"
    ]

    monkeypatch.setattr(sys, "stdout", original_stdout)
    assert cli.main(["cockpit", "--workspace", str(workspace), "--once"]) == 0
    assert (workspace / ".research-agent" / "state.db").is_file()
