from __future__ import annotations

import io
import json
import sys
import tomllib

from claudescientist import agent_hosts, codex_hooks


def test_normalize_agent_host_aliases():
    assert agent_hosts.normalize_agent_host("claudecode") == "claude"
    assert agent_hosts.normalize_agent_host("codex-cli") == "codex"
    assert agent_hosts.normalize_agent_host("all") == "both"
    assert agent_hosts.normalize_agent_host("unknown") == "claude"


def test_build_codex_config_is_valid_toml(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    config = tomllib.loads(agent_hosts.build_codex_config(repo))

    assert config["features"]["hooks"] is True
    assert config["features"]["multi_agent"] is True
    assert config["mcp_servers"]["memory"]["args"] == [
        "run",
        "python",
        "-m",
        "memory_mcp.dev_server",
    ]
    assert config["mcp_servers"]["memory"]["cwd"] == str(repo.resolve())
    assert config["mcp_servers"]["lean"]["cwd"] == str(repo.resolve())
    assert config["mcp_servers"]["openalex"]["command"] == "npx"
    pre_tool_hooks = config["hooks"]["PreToolUse"]
    assert any("leakage_guard" in item["hooks"][0]["command"] for item in pre_tool_hooks)


def test_ensure_codex_support_syncs_agents_and_skills(tmp_path):
    repo = tmp_path
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    agents = repo / ".claude" / "agents"
    skills = repo / ".claude" / "skills" / "demo"
    agents.mkdir(parents=True)
    skills.mkdir(parents=True)
    (agents / "researcher.md").write_text(
        "---\n"
        "name: researcher\n"
        "description: Read-only research helper.\n"
        "tools: Read, mcp__memory__query_literature\n"
        "---\n\n"
        "Never write files.\n",
        encoding="utf-8",
    )
    (skills / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill.\n---\n\nUse the demo workflow.\n",
        encoding="utf-8",
    )

    result = agent_hosts.ensure_codex_support(repo)

    assert repo / ".codex" / "config.toml" in result.written
    codex_config = tomllib.loads((repo / ".codex" / "config.toml").read_text())
    assert codex_config["mcp_servers"]["memory"]["cwd"] == str(repo.resolve())
    agent_text = (repo / ".codex" / "agents" / "researcher.toml").read_text(
        encoding="utf-8"
    )
    agent_config = tomllib.loads(agent_text)
    assert agent_config["name"] == "researcher"
    assert "Never write files" in agent_config["developer_instructions"]
    assert "mcp__memory__query_literature" in agent_config["developer_instructions"]
    assert (repo / ".agents" / "skills" / "demo" / "SKILL.md").exists()

    second = agent_hosts.ensure_codex_support(repo)
    assert second.written == ()


def test_codex_hook_payload_normalization_for_shell_command():
    payload = codex_hooks.normalize_payload(
        {
            "hookEventName": "PreToolUse",
            "toolName": "exec_command",
            "input": {"cmd": "git reset --hard HEAD"},
        }
    )

    assert payload["hook_event_name"] == "PreToolUse"
    assert payload["tool_name"] == "Bash"
    assert payload["tool_input"]["command"] == "git reset --hard HEAD"


def test_codex_hook_runner_reuses_destructive_guard(monkeypatch):
    stdin = io.StringIO(
        json.dumps(
            {
                "hookEventName": "PreToolUse",
                "toolName": "exec_command",
                "input": {"cmd": "git reset --hard HEAD"},
            }
        )
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert codex_hooks.main(["destructive_bash_guard", "--event", "PreToolUse"]) == 0
    payload = json.loads(stdout.getvalue())
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_codex_hook_runner_accepts_powershell_bom(monkeypatch):
    stdin = io.StringIO(
        "\ufeff"
        + json.dumps(
            {
                "hookEventName": "PreToolUse",
                "toolName": "exec_command",
                "input": {"cmd": "git reset --hard HEAD"},
            }
        )
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert codex_hooks.main(["destructive_bash_guard", "--event", "PreToolUse"]) == 0
    payload = json.loads(stdout.getvalue())
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_codex_hook_runner_accepts_misdecoded_powershell_bom(monkeypatch):
    payload_text = json.dumps(
        {
            "hookEventName": "PreToolUse",
            "toolName": "exec_command",
            "input": {"cmd": "git reset --hard HEAD"},
        }
    )
    stdin = io.StringIO(
        "\u9518\u7e36"
        + payload_text.removeprefix("{")
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert codex_hooks.main(["destructive_bash_guard", "--event", "PreToolUse"]) == 0
    payload = json.loads(stdout.getvalue())
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_codex_hook_runner_denies_invalid_json_for_safety_hooks(monkeypatch):
    stdin = io.StringIO('{"hookEventName": "PreToolUse",')
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert codex_hooks.main(["destructive_bash_guard", "--event", "PreToolUse"]) == 0
    payload = json.loads(stdout.getvalue())
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "invalid hook payload" in payload["hookSpecificOutput"]["permissionDecisionReason"]


def test_codex_hook_runner_denies_non_object_payload_for_safety_hooks(monkeypatch):
    stdin = io.StringIO("[]")
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert codex_hooks.main(["leakage_guard", "--event", "PreToolUse"]) == 0
    payload = json.loads(stdout.getvalue())
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
