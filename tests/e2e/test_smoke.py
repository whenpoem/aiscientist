from __future__ import annotations

import json
from pathlib import Path

from cockpit.app import render_snapshot
from cockpit.tui import main as tui_main


def test_cockpit_tui_once_snapshot(workspace, capsys):
    memory_impl = workspace["memory_mcp.impl"]
    hypothesis = memory_impl.propose_hypothesis("Try dropout scaling for ViT")

    exit_code = tui_main(["--once"])
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "research-cockpit" in captured
    assert "Hypothesis Tree" in captured
    assert hypothesis["node_id"] in captured
    assert hypothesis["node_id"] in render_snapshot()


def test_claude_settings_register_stdio_cockpit_and_node_openalex():
    settings_path = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    cockpit = settings["mcpServers"]["cockpit"]
    assert cockpit["command"] == "uv"
    assert cockpit["args"] == ["run", "python", "-m", "cockpit.mcp_server"]

    openalex = settings["mcpServers"]["openalex"]
    assert openalex["command"] == "npx"
    assert openalex["args"] == ["-y", "openalex-research-mcp"]

    expected_hooks = {
        "uv run python \"$CLAUDE_PROJECT_DIR/.claude/hooks/leakage_guard.py\"",
        "uv run python \"$CLAUDE_PROJECT_DIR/.claude/hooks/destructive_bash_guard.py\"",
        "uv run python \"$CLAUDE_PROJECT_DIR/.claude/hooks/provenance_log.py\"",
        "uv run python \"$CLAUDE_PROJECT_DIR/.claude/hooks/intervention_pump.py\"",
        "uv run python \"$CLAUDE_PROJECT_DIR/.claude/hooks/stop_flush.py\"",
    }
    actual_commands = {
        hook["command"]
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    }
    assert expected_hooks <= actual_commands
