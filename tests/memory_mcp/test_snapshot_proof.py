"""Snapshot tool covers the proof trunk (F3 / Plan v2).

`replay.snapshot()` must:
- include `proposition` nodes in `active_frontier`
- list recent `proof_skeleton` drafts under `payload.proof_drafts`
- aggregate `prv_diagnostic_manifests` and `prv_lean_attempts`
- track `prv_corpus_problems` count
- gracefully degrade on legacy v3.0 DBs that lack the prv_* tables
"""

from __future__ import annotations

import json


def _seed_question(con, qid="q_proof_snapshot"):
    con.execute(
        """
        INSERT INTO mem_nodes(node_id, kind, text, state, created_by)
        VALUES(?, 'question', ?, 'active', 'test')
        """,
        (qid, "Does dropout act as approximate Bayesian inference?"),
    )
    return qid


def test_snapshot_includes_proposition_in_frontier(workspace):
    memory_db = workspace["memory_mcp.db"]
    memory = workspace["memory_mcp.impl"]
    prove = workspace["prove_mcp.impl"]

    con = memory_db._connect()
    try:
        qid = _seed_question(con)
    finally:
        con.close()

    prop = prove.propose_proposition(
        "Sample mean is unbiased under iid integrability.", parent_id=qid
    )
    snap = memory.snapshot(label="with_proposition")
    payload = _load_payload(memory_db, snap["snapshot_id"])
    frontier_ids = {row["node_id"] for row in payload["active_frontier"]}
    assert prop["node_id"] in frontier_ids


def test_snapshot_lists_proof_drafts_and_manifests(workspace):
    memory_db = workspace["memory_mcp.db"]
    memory = workspace["memory_mcp.impl"]
    prove = workspace["prove_mcp.impl"]

    con = memory_db._connect()
    try:
        qid = _seed_question(con, "q_proof_two")
    finally:
        con.close()

    prop = prove.propose_proposition("Markov inequality.", parent_id=qid)
    skel = prove.propose_proof_skeleton(
        prop["node_id"], "Use indicator decomposition + integrate."
    )
    draft = prove.register_proof_draft(skel["node_id"], "Step 1. Step 2. Step 3.")
    seg = prove.segment_proof(
        draft["node_id"],
        ["Step 1.", "Step 2.", "Step 3."],
    )
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][0], False, "ok")
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][1], False, "ok")
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][2], False, "ok")
    prove.finalize_manifest(seg["manifest_id"])

    triage = prove.triage_for_formalization(prop["node_id"])
    prove.record_lean_attempt(
        proposition_id=prop["node_id"],
        status="verified",
        lean_source="theorem markov := by ...",
        duration_sec=12.5,
        triage=triage,
    )

    snap = memory.snapshot(label="proof_workflow")
    payload = _load_payload(memory_db, snap["snapshot_id"])

    draft_ids = {row["node_id"] for row in payload["proof_drafts"]}
    assert skel["node_id"] in draft_ids
    assert draft["node_id"] in draft_ids

    manifest_ids = {row["manifest_id"] for row in payload["proof_manifests"]}
    assert seg["manifest_id"] in manifest_ids

    lean_statuses = {row["status"] for row in payload["proof_lean_attempts"]}
    assert "verified" in lean_statuses

    counts = payload["counts"]
    assert counts["proof_drafts"] >= 2
    assert counts["proof_manifests"] >= 1
    assert counts["proof_lean_attempts"] >= 1


def test_snapshot_proof_corpus_count(workspace):
    memory = workspace["memory_mcp.impl"]
    prove = workspace["prove_mcp.impl"]

    prove.ingest_proof_corpus(
        source="manual",
        problems=[
            {
                "problem_id": "snap_p1",
                "statement": "Markov bound for non-negative X.",
                "lexical_keywords": ["markov"],
            }
        ],
    )
    snap = memory.snapshot(label="with_corpus")
    counts = snap["counts"]
    assert counts["proof_corpus"] >= 1


def test_snapshot_safe_on_missing_prv_tables(workspace, monkeypatch):
    """Even when prv_* tables don't exist (v3.0-only DB), snapshot succeeds."""
    memory = workspace["memory_mcp.impl"]
    memory_db = workspace["memory_mcp.db"]

    # Drop prv_* tables to simulate a legacy DB.
    con = memory_db._connect()
    try:
        for table in (
            "prv_lean_attempts",
            "prv_diagnostic_manifests",
            "prv_corpus_keywords",
            "prv_corpus_problems",
        ):
            try:
                con.execute(f"DROP TABLE IF EXISTS {table}")
            except Exception:  # noqa: BLE001
                pass
        con.commit()
    finally:
        con.close()

    snap = memory.snapshot(label="legacy")
    counts = snap["counts"]
    assert counts["proof_corpus"] == 0
    assert counts["proof_drafts"] == 0
    assert counts["proof_manifests"] == 0
    assert counts["proof_lean_attempts"] == 0


def _load_payload(memory_db, snapshot_id: str) -> dict:
    con = memory_db._connect()
    try:
        row = con.execute(
            "SELECT payload FROM mem_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    finally:
        con.close()
    return json.loads(row["payload"])
