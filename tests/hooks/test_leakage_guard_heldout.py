from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
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


def test_leakage_guard_cannot_be_bypassed_by_verify_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("RESEARCH_AGENT_VERIFY", "1")
    module = _load_hook("leakage_guard")
    module.DB = tmp_path / "state.db"

    heldout_path = tmp_path / ".research-agent" / "heldout" / "eval.csv"
    payload = _run_hook(
        module,
        {"tool_input": {"path": str(heldout_path)}},
        monkeypatch,
    )

    _assert_heldout_deny(payload)


def test_leakage_guard_blocks_custom_heldout_root_from_env(tmp_path, monkeypatch):
    custom_root = tmp_path / "private-heldout"
    monkeypatch.setenv("RESEARCH_AGENT_HELDOUT_DIR", str(custom_root))
    module = _load_hook("leakage_guard")
    module.DB = tmp_path / "state.db"

    payload = _run_hook(
        module,
        {"tool_input": {"path": str(custom_root / "mnist-test" / "labels.csv")}},
        monkeypatch,
    )

    _assert_heldout_deny(payload)


def test_leakage_guard_blocks_registered_heldout_path_from_db(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    module = _load_hook("leakage_guard")
    module.DB = tmp_path / "state.db"
    registered_root = tmp_path / "custom-heldout" / "mnist-test"
    con = sqlite3.connect(str(module.DB))
    try:
        con.execute(
            """
            CREATE TABLE ver_heldout_budgets (
              dataset TEXT PRIMARY KEY,
              heldout_path TEXT NOT NULL
            )
            """
        )
        con.execute(
            "INSERT INTO ver_heldout_budgets(dataset, heldout_path) VALUES(?,?)",
            ("mnist-test", str(registered_root)),
        )
        con.commit()
    finally:
        con.close()

    payload = _run_hook(
        module,
        {"tool_input": {"command": f"type {registered_root / 'labels.csv'}"}},
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
