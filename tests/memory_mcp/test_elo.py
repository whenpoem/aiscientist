from __future__ import annotations

import importlib
import inspect

from claudescientist.runtime import connect_sqlite


def test_judge_hypotheses_returns_structured_prompt(workspace):
    impl = workspace["memory_mcp.impl"]

    a_node = impl.propose_hypothesis("Sparse attention improves long-context scaling")["node_id"]
    b_node = impl.propose_hypothesis("Curriculum learning reduces optimizer instability")[
        "node_id"
    ]

    result = impl.judge_hypotheses(a_node, b_node)

    assert result["hypothesis_a"]["node_id"] == a_node
    assert result["hypothesis_b"]["node_id"] == b_node
    assert result["criteria"] == ["novelty", "feasibility", "falsifiability"]
    assert a_node in result["prompt"]
    assert b_node in result["prompt"]


def test_record_judgement_updates_elo_and_persists_ledger(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    node_a = impl.propose_hypothesis("Use stronger augmentations for ViT warmup")["node_id"]
    node_b = impl.propose_hypothesis("Tune dropout schedule instead of fixed dropout")["node_id"]
    node_c = impl.propose_hypothesis("Scale patch size with data regime")["node_id"]

    impl.record_judgement(node_a, node_b, node_a, reason="A is easier to falsify")
    impl.record_judgement(node_a, node_c, node_c, reason="C is more novel")
    impl.record_judgement(node_b, node_c, node_c, reason="C dominates B")

    con = db._connect()
    try:
        rows = con.execute(
            "SELECT node_id, elo_score FROM mem_nodes WHERE node_id IN (?,?,?)",
            (node_a, node_b, node_c),
        ).fetchall()
        judgements = con.execute(
            "SELECT a_node_id, b_node_id, winner_node_id, reason FROM mem_judgements "
            "ORDER BY judgement_id"
        ).fetchall()
    finally:
        con.close()

    scores = {row["node_id"]: row["elo_score"] for row in rows}
    assert scores[node_c] > scores[node_a] > scores[node_b]
    assert [dict(row) for row in judgements] == [
        {
            "a_node_id": node_a,
            "b_node_id": node_b,
            "winner_node_id": node_a,
            "reason": "A is easier to falsify",
        },
        {
            "a_node_id": node_a,
            "b_node_id": node_c,
            "winner_node_id": node_c,
            "reason": "C is more novel",
        },
        {
            "a_node_id": node_b,
            "b_node_id": node_c,
            "winner_node_id": node_c,
            "reason": "C dominates B",
        },
    ]


def test_memory_bootstrap_adds_elo_column_for_existing_db(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    con = connect_sqlite(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE mem_nodes (
              node_id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              text TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by TEXT NOT NULL DEFAULT 'claude',
              parent_id TEXT
            );
            """
        )
    finally:
        con.close()

    monkeypatch.setenv("RESEARCH_AGENT_DB_PATH", str(db_path))
    db = importlib.reload(importlib.import_module("memory_mcp.db"))
    impl = importlib.reload(importlib.import_module("memory_mcp.impl"))
    db.bootstrap()

    con = db._connect()
    try:
        columns = {
            row["name"]: row["type"]
            for row in con.execute("PRAGMA table_info(mem_nodes)").fetchall()
        }
        ledger = con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'mem_judgements'"
        ).fetchone()
    finally:
        con.close()

    assert columns["elo_score"] == "REAL"
    assert ledger is not None

    node_id = impl.propose_hypothesis(
        "Bootstrap migrated DB can still insert hypotheses"
    )["node_id"]
    frontier = impl.get_active_frontier()
    assert frontier[0]["node_id"] == node_id
    assert frontier[0]["elo_score"] == 1500.0


def test_memory_dev_server_preserves_elo_tool_signatures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    impl = importlib.reload(importlib.import_module("memory_mcp.impl"))
    dev_server = importlib.reload(importlib.import_module("memory_mcp.dev_server"))

    assert inspect.signature(dev_server.judge_hypotheses) == inspect.signature(
        impl.judge_hypotheses
    )
    assert inspect.signature(dev_server.record_judgement) == inspect.signature(
        impl.record_judgement
    )
