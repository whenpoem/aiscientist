"""BT comparison kind semantics (P1 / ADR 0008).

BT_RANKABLE_KINDS = (hypothesis, proof_skeleton). Same-kind comparison is
allowed for either kind; cross-kind comparison is forbidden so the
leaderboard semantics stay coherent.

record_judgement and judge_hypotheses remain hypothesis-only — proof-trunk
callers reach BT through update_bt_rating directly, since they don't have
the legacy Elo dual-write requirement.
"""

from __future__ import annotations

import pytest


def _insert_skeleton(con, node_id: str, text: str) -> None:
    con.execute(
        """
        INSERT INTO mem_nodes(node_id, kind, text, state, created_by, parent_id)
        VALUES(?,?,?,?,?,?)
        """,
        (node_id, "proof_skeleton", text, "active", "test", None),
    )
    con.execute(
        "INSERT OR IGNORE INTO mem_bt_ratings(node_id) VALUES(?)",
        (node_id,),
    )


def test_update_bt_rating_allows_proof_skeleton_pair(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    con = db._connect()
    try:
        _insert_skeleton(con, "psk_a", "skeleton A: linearity of expectation")
        _insert_skeleton(con, "psk_b", "skeleton B: characteristic functions")
    finally:
        con.close()

    result = impl.update_bt_rating("psk_a", "psk_b", source="reviewer_critic")
    assert result["winner"]["node_id"] == "psk_a"
    assert result["winner"]["strength"] > result["loser"]["strength"]


def test_update_bt_rating_forbids_cross_kind(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    hyp = impl.propose_hypothesis("dropout helps small data")["node_id"]
    con = db._connect()
    try:
        _insert_skeleton(con, "psk_x", "some proof skeleton")
    finally:
        con.close()

    with pytest.raises(ValueError, match="cross-kind"):
        impl.update_bt_rating(hyp, "psk_x", source="reviewer_critic")
    with pytest.raises(ValueError, match="cross-kind"):
        impl.update_bt_rating("psk_x", hyp, source="reviewer_critic")


def test_update_bt_rating_rejects_non_rankable_kind(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    a = impl.propose_hypothesis("anchor hypothesis")["node_id"]
    con = db._connect()
    try:
        # Question nodes are not rankable.
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by, parent_id)
            VALUES(?,?,?,?,?,?)
            """,
            ("q_x", "question", "what should we study?", "active", "test", None),
        )
    finally:
        con.close()

    with pytest.raises(ValueError, match="BT_RANKABLE_KINDS|require kinds"):
        impl.update_bt_rating(a, "q_x", source="reviewer_critic")


def test_get_bt_leaderboard_default_returns_hypotheses_only(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    impl.propose_hypothesis("hyp lead")
    con = db._connect()
    try:
        _insert_skeleton(con, "psk_lead", "skeleton lead")
    finally:
        con.close()

    board = impl.get_bt_leaderboard(top_k=10)
    kinds = {row["kind"] for row in board}
    assert kinds == {"hypothesis"}


def test_get_bt_leaderboard_proof_skeleton_view(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    impl.propose_hypothesis("hyp lead")
    con = db._connect()
    try:
        _insert_skeleton(con, "psk_a", "skeleton A")
        _insert_skeleton(con, "psk_b", "skeleton B")
    finally:
        con.close()
    impl.update_bt_rating("psk_a", "psk_b", source="reviewer_critic")

    board = impl.get_bt_leaderboard(top_k=10, kind="proof_skeleton")
    kinds = {row["kind"] for row in board}
    assert kinds == {"proof_skeleton"}
    ids = {row["node_id"] for row in board}
    assert ids == {"psk_a", "psk_b"}


def test_get_bt_leaderboard_rejects_unknown_kind(workspace):
    impl = workspace["memory_mcp.impl"]

    with pytest.raises(ValueError):
        impl.get_bt_leaderboard(kind="evidence")


def test_record_judgement_still_hypothesis_only(workspace):
    """record_judgement gates on hypothesis (its own check, not _bt_apply_comparison's)."""
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    a = impl.propose_hypothesis("anchor a")["node_id"]
    con = db._connect()
    try:
        _insert_skeleton(con, "psk_judge", "skeleton")
    finally:
        con.close()

    with pytest.raises(ValueError, match="record_judgement only supports hypothesis"):
        impl.record_judgement(a, "psk_judge", winner_node_id=a)


def test_expected_information_gain_filters_candidates_to_requested_kind(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    hyp = impl.propose_hypothesis("anchor hypothesis")["node_id"]
    con = db._connect()
    try:
        _insert_skeleton(con, "psk_eig_a", "skeleton A")
        _insert_skeleton(con, "psk_eig_b", "skeleton B")
    finally:
        con.close()

    scores = impl.expected_information_gain(
        [hyp, "psk_eig_a", "psk_eig_b"],
        kind="proof_skeleton",
    )
    assert {row["node_id"] for row in scores} == {"psk_eig_a", "psk_eig_b"}
