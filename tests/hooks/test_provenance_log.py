from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

from cockpit.db import connect, ensure


def _load_hook(name: str):
    hook_path = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, hook_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_hook(module, payload: dict[str, object], monkeypatch) -> str:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    module.main()
    return stdout.getvalue()


def test_provenance_log_collects_labeled_metrics_only(workspace, monkeypatch):
    ensure()
    module = _load_hook("provenance_log")
    payload = {
        "tool_name": "Bash",
        "session_id": "sess-2",
        "tool_input": {"command": "python train.py"},
        "tool_output": {
            "stdout": "\n".join(
                [
                    "Epoch 3/10",
                    "seed: 42",
                    "Validation Accuracy: 91.2%",
                    "F1 score 0.812",
                    "test auc = 0.934",
                ]
            ),
            "stderr": "loss is 0.125\nthroughput: 120/s",
        },
    }

    records = module.collect_records(payload)
    assert records == [
        ("validation_accuracy", "91.2%", "sess-2", "python train.py"),
        ("f1_score", "0.812", "sess-2", "python train.py"),
        ("test_auc", "0.934", "sess-2", "python train.py"),
        ("loss", "0.125", "sess-2", "python train.py"),
    ]

    _run_hook(module, payload, monkeypatch)

    con = connect()
    try:
        rows = con.execute(
            """
            SELECT claim, value, session_id, source_command
            FROM ver_provenance
            ORDER BY id
            """
        ).fetchall()
    finally:
        con.close()

    assert [tuple(row) for row in rows] == records


def test_provenance_log_ignores_non_metric_noise(workspace):
    ensure()
    module = _load_hook("provenance_log")
    payload = {
        "tool_name": "Bash",
        "session_id": "sess-3",
        "tool_input": {"command": "python benchmark.py"},
        "tool_output": {
            "stdout": "epoch=12\nseed=7\nbatch size 64\ntime: 3.2s",
            "stderr": "",
        },
    }

    assert module.collect_records(payload) == []
