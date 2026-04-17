from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path


def _load_hook(name: str):
    hook_path = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, hook_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_hook(module, payload: dict[str, object], monkeypatch) -> dict[str, object]:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    module.main()
    raw = stdout.getvalue().strip() or "{}"
    return json.loads(raw)


def test_intervention_pump_user_prompt_submit_uses_structured_context(workspace, monkeypatch):
    workspace["cockpit.db"].ensure()
    con = workspace["cockpit.db"].connect()
    try:
        con.execute(
            "INSERT INTO cockpit_interventions(kind, target, payload) VALUES(?,?,?)",
            ("redirect", "hyp_1", "look at the baseline instead"),
        )
        con.commit()
    finally:
        con.close()

    module = _load_hook("intervention_pump")
    payload = _run_hook(
        module,
        {"hook_event_name": "UserPromptSubmit", "session_id": "sess-1"},
        monkeypatch,
    )

    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "look at the baseline instead" in payload["hookSpecificOutput"]["additionalContext"]


def test_intervention_pump_stop_is_a_noop(workspace, monkeypatch):
    workspace["cockpit.db"].ensure()
    con = workspace["cockpit.db"].connect()
    try:
        con.execute(
            "INSERT INTO cockpit_interventions(kind, target, payload) VALUES(?,?,?)",
            ("halt", "hyp_2", "stop here"),
        )
        con.commit()
    finally:
        con.close()

    module = _load_hook("intervention_pump")
    payload = _run_hook(module, {"hook_event_name": "Stop", "session_id": "sess-2"}, monkeypatch)

    assert payload == {}

    con = workspace["cockpit.db"].connect()
    try:
        row = con.execute(
            "SELECT delivered_at FROM cockpit_interventions WHERE target = ?",
            ("hyp_2",),
        ).fetchone()
    finally:
        con.close()

    assert row is not None
    assert row["delivered_at"] is None


def test_leakage_guard_returns_structured_pretooluse_deny(monkeypatch):
    module = _load_hook("leakage_guard")
    payload = _run_hook(
        module,
        {
            "tool_input": {
                "path": r"C:\\Users\\whenpoem\\.research-agent\\held_out\\eval.csv",
                "content": "ignored",
            }
        },
        monkeypatch,
    )

    assert payload == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Held-out data access is restricted to verify-mcp.",
        }
    }


def test_leakage_guard_ignores_unlabeled_markdown_numbers(monkeypatch):
    module = _load_hook("leakage_guard")
    payload = _run_hook(
        module,
        {
            "tool_input": {
                "file_path": "reports/summary.md",
                "content": "In 2026 we ran 3 baselines across 4 seeds.",
            }
        },
        monkeypatch,
    )

    assert payload == {}


def test_leakage_guard_blocks_unproven_labeled_markdown_metrics(monkeypatch):
    module = _load_hook("leakage_guard")
    payload = _run_hook(
        module,
        {
            "tool_input": {
                "file_path": "reports/summary.md",
                "content": "Validation Accuracy: 91.2%\nLoss = 0.12",
            }
        },
        monkeypatch,
    )

    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "91.2%" in payload["hookSpecificOutput"]["permissionDecisionReason"]


def test_destructive_bash_guard_returns_structured_pretooluse_deny(monkeypatch):
    module = _load_hook("destructive_bash_guard")
    payload = _run_hook(
        module,
        {"tool_input": {"command": "git reset --hard HEAD~1"}},
        monkeypatch,
    )

    assert payload == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Destructive bash command blocked. Append # CONFIRM_DESTRUCTIVE to proceed."
            ),
        }
    }
