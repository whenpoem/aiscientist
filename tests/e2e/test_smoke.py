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


def test_cockpit_tui_once_snapshot_zh(workspace, capsys):
    memory_impl = workspace["memory_mcp.impl"]
    hypothesis = memory_impl.propose_hypothesis("Try dropout scaling for ViT")

    exit_code = tui_main(["--once", "--lang", "zh"])
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "研究座舱" in captured
    assert "假设树" in captured
    assert hypothesis["node_id"] in captured


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


def test_sops_reference_selection_flow():
    """V3.0: research-sop must reference bt-tournament (with elo-select kept as a shim)."""
    repo_root = Path(__file__).resolve().parents[2]
    research_sop = (repo_root / ".claude" / "skills" / "research-sop" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    writeup_sop = (repo_root / ".claude" / "skills" / "writeup-sop" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    bt_tournament = (
        repo_root / ".claude" / "skills" / "bt-tournament" / "SKILL.md"
    ).read_text(encoding="utf-8")
    elo_select = (repo_root / ".claude" / "skills" / "elo-select" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    verifier = (repo_root / ".claude" / "agents" / "verifier.md").read_text(
        encoding="utf-8"
    )

    # V3.0 primary path
    assert "$bt-tournament" in research_sop
    assert "$preregister" in research_sop
    assert "mcp__memory__judge_hypotheses" in research_sop
    assert "mcp__memory__record_judgement" in research_sop
    assert "mcp__memory__get_bt_leaderboard" in bt_tournament
    # Backwards-compat shim still recognised
    assert "deprecated" in elo_select.lower()
    assert "mcp__memory__record_judgement" in elo_select
    # Writeup SOP still references the legacy shim until P5 polish updates it
    assert "elo-select" in writeup_sop or "bt-tournament" in writeup_sop
    # Verifier tool whitelist unchanged in P4
    assert "mcp__verify__seed_perturb" in verifier
    assert "mcp__verify__baseline_fairness" in verifier
    assert "mcp__verify__query_heldout" in verifier
