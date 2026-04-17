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


def _assert_heldout_deny(payload: dict[str, object]) -> None:
    assert payload == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "held-out dataset access only via query_heldout",
        }
    }


def test_leakage_guard_blocks_direct_heldout_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    module = _load_hook("leakage_guard")
    module.DB = tmp_path / "state.db"

    heldout_path = tmp_path / ".research-agent" / "heldout" / "eval.csv"
    payload = _run_hook(
        module,
        {"tool_input": {"path": str(heldout_path), "content": "ignored"}},
        monkeypatch,
    )

    _assert_heldout_deny(payload)


def test_leakage_guard_blocks_pointer_file_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    module = _load_hook("leakage_guard")
    module.DB = tmp_path / "state.db"

    pointer_file = tmp_path / "notes.heldout-pointer"
    payload = _run_hook(
        module,
        {"tool_input": {"path": str(pointer_file)}},
        monkeypatch,
    )

    _assert_heldout_deny(payload)


def test_leakage_guard_blocks_heldout_paths_in_bash_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    module = _load_hook("leakage_guard")
    module.DB = tmp_path / "state.db"

    heldout_path = tmp_path / ".research-agent" / "heldout" / "eval.csv"
    payload = _run_hook(
        module,
        {"tool_input": {"command": f"type {heldout_path}"}},
        monkeypatch,
    )

    _assert_heldout_deny(payload)
