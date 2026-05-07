"""propose_proposition / propose_proof_skeleton / register_proof_draft (P3)."""

from __future__ import annotations

import pytest


def test_propose_proposition_creates_node(workspace):
    impl = workspace["prove_mcp.impl"]
    db = workspace["memory_mcp.db"]

    result = impl.propose_proposition("E[X̄] = μ for iid samples")
    node_id = result["node_id"]
    assert node_id.startswith("prop_")

    con = db._connect()
    try:
        row = con.execute(
            "SELECT kind, text, state FROM mem_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        con.close()
    assert row["kind"] == "proposition"
    assert row["text"].startswith("E[")
    assert row["state"] == "active"


def test_propose_proposition_can_attach_to_question_node(workspace):
    """Empirical hypothesis and theoretical proposition share one tree."""
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    # Make a question node directly (memory_mcp doesn't expose a tool for
    # this; a question is set up through the research-sop manually or via
    # raw insert in tests).
    con = db._connect()
    try:
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by)
            VALUES('q_root', 'question', 'Does dropout help small data?', 'active', 'test')
            """
        )
    finally:
        con.close()

    hyp = memory.propose_hypothesis("dropout reduces test error", parent_id="q_root")
    prop = prove.propose_proposition(
        "dropout is approximate Bayesian inference",
        parent_id="q_root",
    )
    # Both should be siblings under q_root.
    con = db._connect()
    try:
        rows = con.execute(
            "SELECT node_id, kind FROM mem_nodes WHERE parent_id = 'q_root' "
            "ORDER BY kind, node_id"
        ).fetchall()
    finally:
        con.close()
    by_id = {row["node_id"]: row["kind"] for row in rows}
    assert by_id[hyp["node_id"]] == "hypothesis"
    assert by_id[prop["node_id"]] == "proposition"


def test_propose_proposition_rejects_empty_text(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="non-empty"):
        impl.propose_proposition("   ")


def test_propose_proof_skeleton_seeds_bt_row(workspace):
    impl = workspace["prove_mcp.impl"]
    db = workspace["memory_mcp.db"]

    prop = impl.propose_proposition("Sample mean is unbiased")
    skel = impl.propose_proof_skeleton(prop["node_id"], "Use linearity of E[].")
    assert skel["node_id"].startswith("psk_")

    con = db._connect()
    try:
        bt = con.execute(
            "SELECT strength, strength_var, status FROM mem_bt_ratings "
            "WHERE node_id = ?",
            (skel["node_id"],),
        ).fetchone()
        node = con.execute(
            "SELECT kind, parent_id FROM mem_nodes WHERE node_id = ?",
            (skel["node_id"],),
        ).fetchone()
    finally:
        con.close()
    assert bt is not None
    assert bt["strength"] == 0.0
    assert bt["status"] == "active"
    assert node["kind"] == "proof_skeleton"
    assert node["parent_id"] == prop["node_id"]


def test_propose_proof_skeleton_requires_proposition_parent(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]

    hyp = memory.propose_hypothesis("dropout helps small data")
    with pytest.raises(ValueError, match="proposition parent"):
        prove.propose_proof_skeleton(hyp["node_id"], "skeleton")


def test_propose_proof_skeleton_unknown_proposition(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="Unknown proposition"):
        impl.propose_proof_skeleton("prop_does_not_exist", "skeleton")


def test_register_proof_draft_creates_child_skeleton(workspace):
    impl = workspace["prove_mcp.impl"]
    db = workspace["memory_mcp.db"]

    prop = impl.propose_proposition("CLT for iid samples")
    skel = impl.propose_proof_skeleton(prop["node_id"], "5-step outline")
    draft = impl.register_proof_draft(skel["node_id"], "Full LaTeX draft body")
    assert draft["node_id"].startswith("psk_")
    assert draft["parent_skeleton_id"] == skel["node_id"]

    con = db._connect()
    try:
        row = con.execute(
            "SELECT kind, parent_id, text FROM mem_nodes WHERE node_id = ?",
            (draft["node_id"],),
        ).fetchone()
    finally:
        con.close()
    assert row["kind"] == "proof_skeleton"
    assert row["parent_id"] == skel["node_id"]
    assert row["text"] == "Full LaTeX draft body"


def test_register_proof_draft_requires_skeleton_parent(workspace):
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition("foo")
    # parent must be a proof_skeleton, not a proposition
    with pytest.raises(ValueError, match="proof_skeleton parent"):
        impl.register_proof_draft(prop["node_id"], "draft body")


def test_list_proof_drafts_returns_deepest_descendant_first(workspace):
    impl = workspace["prove_mcp.impl"]

    prop = impl.propose_proposition("variance bound under finite moments")
    skel = impl.propose_proof_skeleton(prop["node_id"], "outline")
    draft = impl.register_proof_draft(skel["node_id"], "first full draft")
    corrected = impl.register_proof_draft(draft["node_id"], "corrected full draft")

    rows = impl.list_proof_drafts(prop["node_id"])
    assert [row["node_id"] for row in rows[:3]] == [
        corrected["node_id"],
        draft["node_id"],
        skel["node_id"],
    ]
    assert rows[0]["depth"] == 3


def test_list_proof_drafts_rejects_non_proposition(workspace):
    impl = workspace["prove_mcp.impl"]

    prop = impl.propose_proposition("sample mean unbiased")
    skel = impl.propose_proof_skeleton(prop["node_id"], "outline")

    with pytest.raises(ValueError, match="expects a proposition"):
        impl.list_proof_drafts(skel["node_id"])
