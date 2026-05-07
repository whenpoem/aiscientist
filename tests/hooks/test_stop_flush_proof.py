"""stop_flush hook reports proof-trunk activity (F3 / Plan v2).

The end-of-turn digest aggregates `prv_diagnostic_manifests` and
`prv_lean_attempts` so a long-running session sees stale manifests and
recent Lean activity in its summary, and the cockpit can render running
totals.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
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


def _latest_event(con) -> dict:
    row = con.execute(
        "SELECT payload FROM cockpit_events WHERE kind = 'turn_end' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    return json.loads(row["payload"])


def test_digest_counts_proof_manifests_and_lean_attempts(workspace, monkeypatch):
    ensure()
    prove = workspace["prove_mcp.impl"]

    # Seed a question + proposition + skeleton + draft + segmented manifest +
    # a Lean attempt so the digest has something to count.
    con = connect()
    try:
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by)
            VALUES('q_t', 'question', 'parent', 'active', 'test')
            """
        )
        con.commit()
    finally:
        con.close()

    prop = prove.propose_proposition("Markov inequality.", parent_id="q_t")
    skel = prove.propose_proof_skeleton(prop["node_id"], "outline")
    draft = prove.register_proof_draft(skel["node_id"], "draft body")
    seg = prove.segment_proof(draft["node_id"], ["s1", "s2"])
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][0], False, "ok")
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][1], False, "ok")
    prove.finalize_manifest(seg["manifest_id"])

    triage = prove.triage_for_formalization(prop["node_id"])
    prove.record_lean_attempt(
        proposition_id=prop["node_id"],
        status="verified",
        lean_source="theorem ok := ...",
        duration_sec=12.0,
        triage=triage,
    )
    prove.record_lean_attempt(
        proposition_id=prop["node_id"],
        status="failed",
        lean_source="theorem nope := ...",
        stderr="error",
        duration_sec=4.0,
        triage=triage,
    )

    module = _load_hook("stop_flush")
    _run_hook(module, {"session_id": "s1", "hook_event_name": "Stop"}, monkeypatch)

    con = connect()
    try:
        digest = _latest_event(con)
    finally:
        con.close()

    summary = digest["summary"]
    assert summary["proof_manifests_total"] >= 1
    assert summary["proof_manifests_empty"] >= 1
    assert summary["lean_attempts_total"] == 2
    assert summary["lean_attempts_verified"] == 1
    assert summary["lean_attempts_failed"] == 1
    assert summary["lean_wallclock_used_sec"] >= 12.0

    counts = digest["delta"]["counts"]
    assert counts["new_proof_manifests"] >= 1
    assert counts["new_lean_attempts"] == 2


def test_digest_safe_when_prv_tables_missing(workspace, monkeypatch):
    """v3.0-only DBs (no prv_* tables) must not crash the hook."""
    ensure()
    # Drop prv_* to simulate legacy DB.
    state_db = workspace["memory_mcp.db"].state_db_path()
    con = sqlite3.connect(str(state_db))
    try:
        for table in (
            "prv_lean_attempts",
            "prv_diagnostic_manifests",
            "prv_corpus_keywords",
            "prv_corpus_problems",
        ):
            con.execute(f"DROP TABLE IF EXISTS {table}")
        con.commit()
    finally:
        con.close()

    module = _load_hook("stop_flush")
    _run_hook(module, {"session_id": "s1", "hook_event_name": "Stop"}, monkeypatch)

    con = connect()
    try:
        digest = _latest_event(con)
    finally:
        con.close()

    summary = digest["summary"]
    assert summary["proof_manifests_total"] == 0
    assert summary["lean_attempts_total"] == 0
    assert summary["lean_wallclock_used_sec"] == 0


def test_digest_lean_wallclock_sums_durations(workspace, monkeypatch):
    ensure()
    prove = workspace["prove_mcp.impl"]
    con = connect()
    try:
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by)
            VALUES('q_w', 'question', 'parent', 'active', 'test')
            """
        )
        con.commit()
    finally:
        con.close()

    prop = prove.propose_proposition("Sum durations.", parent_id="q_w")
    triage = prove.triage_for_formalization(prop["node_id"])
    for dur in (5.5, 7.25, 11.0):
        prove.record_lean_attempt(
            proposition_id=prop["node_id"],
            status="verified",
            lean_source="theorem :=",
            duration_sec=dur,
            triage=triage,
        )

    module = _load_hook("stop_flush")
    _run_hook(module, {"session_id": "s1", "hook_event_name": "Stop"}, monkeypatch)
    con = connect()
    try:
        digest = _latest_event(con)
    finally:
        con.close()
    assert digest["summary"]["lean_wallclock_used_sec"] == 23.75
