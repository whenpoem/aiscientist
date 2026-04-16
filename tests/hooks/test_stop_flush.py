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


def test_stop_flush_persists_useful_delta(workspace, monkeypatch):
    ensure()
    con = connect()
    try:
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state)
            VALUES(?,?,?,?)
            """,
            ("hyp_1", "hypothesis", "Use a stronger baseline.", "active"),
        )
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, parent_id)
            VALUES(?,?,?,?,?)
            """,
            ("ev_1", "evidence", "Validation accuracy improved to 91.2%.", "active", "hyp_1"),
        )
        con.execute(
            """
            INSERT INTO mem_edges(src, dst, relation, rationale)
            VALUES(?,?,?,?)
            """,
            ("hyp_1", "ev_1", "supports", "Observed on the validation split."),
        )
        con.execute(
            """
            INSERT INTO mem_failures(
              trigger, symptom, root_cause, resolution, signature, seen_count
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                "train.py --seed 7",
                "validation collapsed after epoch 2",
                "learning rate too high",
                "lowered lr",
                "collapse-v1",
                1,
            ),
        )
        con.execute(
            """
            INSERT INTO mem_lit_compressed(
              paper_id, source, title, authors, year, venue, problem, method,
              claimed_results, assumptions, limitations, relates_to, raw_abstract
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "paper-1",
                "openalex",
                "A stronger baseline",
                "Doe et al.",
                2025,
                "ICML",
                "classification",
                "baseline",
                "91.2 acc",
                "iid",
                "small dataset",
                "{}",
                "abstract",
            ),
        )
        con.execute(
            """
            INSERT INTO ver_provenance(claim, value, session_id, source_command)
            VALUES(?,?,?,?)
            """,
            ("validation_accuracy", "91.2%", "sess-1", "python train.py"),
        )
        con.commit()
    finally:
        con.close()

    module = _load_hook("stop_flush")
    _run_hook(module, {"session_id": "sess-1", "hook_event_name": "Stop"}, monkeypatch)

    con = connect()
    try:
        event = con.execute(
            "SELECT kind, payload FROM cockpit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()

    assert event is not None
    assert event["kind"] == "turn_end"
    payload = json.loads(event["payload"])
    assert payload["delta"]["counts"]["new_nodes"] == 2
    assert payload["delta"]["counts"]["new_edges"] == 1
    assert payload["delta"]["counts"]["new_failures"] == 1
    assert payload["delta"]["counts"]["new_papers"] == 1
    assert payload["delta"]["counts"]["new_provenance"] == 1
    assert payload["delta"]["new_nodes"][0]["node_id"] == "hyp_1"

    con = connect()
    try:
        con.execute("UPDATE mem_nodes SET state = ? WHERE node_id = ?", ("refuted", "hyp_1"))
        con.execute(
            "UPDATE mem_failures SET seen_count = seen_count + 2 WHERE failure_id = 1"
        )
        con.commit()
    finally:
        con.close()

    _run_hook(module, {"session_id": "sess-1", "hook_event_name": "Stop"}, monkeypatch)

    con = connect()
    try:
        event = con.execute(
            "SELECT payload FROM cockpit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()

    assert event is not None
    payload = json.loads(event["payload"])
    assert payload["delta"]["counts"]["state_changes"] == 1
    assert payload["delta"]["state_changes"][0]["from"] == "active"
    assert payload["delta"]["state_changes"][0]["to"] == "refuted"
    assert payload["delta"]["counts"]["repeated_failures"] == 1
    assert payload["delta"]["repeated_failures"][0]["new_hits"] == 2
