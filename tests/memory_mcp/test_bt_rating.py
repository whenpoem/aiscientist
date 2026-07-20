from __future__ import annotations

import math

import pytest


def test_rounded_probability_distribution_preserves_total(workspace):
    bt = workspace["memory_mcp.tools.bt"]
    rounded = bt._rounded_probability_distribution(  # noqa: SLF001
        {"a": 0.3333334, "b": 0.3333334, "c": 0.3333332, "missing": None}
    )
    assert rounded["missing"] is None
    assert sum(value for value in rounded.values() if value is not None) == 1.0


def test_propose_hypothesis_seeds_bt_row(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    node_id = impl.propose_hypothesis("Larger batch sizes hurt fine-tuning")["node_id"]

    con = db._connect()
    try:
        row = con.execute(
            "SELECT strength, strength_var, n_comparisons, status "
            "FROM mem_bt_ratings WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        con.close()

    assert row is not None
    assert row["strength"] == 0.0
    assert row["strength_var"] == 1.0
    assert row["n_comparisons"] == 0
    assert row["status"] == "active"


def test_update_bt_rating_pushes_winner_above_loser(workspace):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("Add curriculum to stabilize training")["node_id"]
    b = impl.propose_hypothesis("Tune AdamW betas for stability")["node_id"]

    for _ in range(8):
        result = impl.update_bt_rating(a, b, source="llm_judge")
    assert result["winner"]["node_id"] == a
    assert result["winner"]["strength"] > result["loser"]["strength"]
    assert result["winner"]["strength_var"] < 1.0
    assert result["loser"]["strength_var"] < 1.0


def test_update_bt_rating_clip_keeps_strength_bounded(workspace):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("Always wins")["node_id"]
    b = impl.propose_hypothesis("Always loses")["node_id"]

    for _ in range(200):
        impl.update_bt_rating(a, b, source="llm_judge")

    leaderboard = impl.get_bt_leaderboard()
    by_id = {row["node_id"]: row for row in leaderboard}
    assert by_id[a]["strength"] <= 12.0 + 1e-6
    assert by_id[b]["strength"] >= -12.0 - 1e-6
    assert by_id[a]["strength"] > by_id[b]["strength"]


def test_record_judgement_dual_writes_bt_and_elo(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    a = impl.propose_hypothesis("Hypothesis A")["node_id"]
    b = impl.propose_hypothesis("Hypothesis B")["node_id"]

    impl.record_judgement(a, b, a, reason="A clearly stronger")

    con = db._connect()
    try:
        elo_a, elo_b = (
            row["elo_score"]
            for row in con.execute(
                "SELECT node_id, elo_score FROM mem_nodes WHERE node_id IN (?,?) "
                "ORDER BY CASE node_id WHEN ? THEN 0 ELSE 1 END",
                (a, b, a),
            ).fetchall()
        )
        comparison_count = int(
            con.execute("SELECT COUNT(*) FROM mem_bt_comparisons").fetchone()[0]
        )
        bt_a = con.execute(
            "SELECT strength, n_comparisons FROM mem_bt_ratings WHERE node_id = ?",
            (a,),
        ).fetchone()
        bt_b = con.execute(
            "SELECT strength, n_comparisons FROM mem_bt_ratings WHERE node_id = ?",
            (b,),
        ).fetchone()
    finally:
        con.close()

    assert elo_a > elo_b
    assert comparison_count == 1
    assert bt_a["n_comparisons"] == 1
    assert bt_b["n_comparisons"] == 1
    assert bt_a["strength"] > bt_b["strength"]


def test_get_bt_leaderboard_orders_and_marks_insufficient(workspace):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("Strong candidate")["node_id"]
    b = impl.propose_hypothesis("Mid candidate")["node_id"]
    c = impl.propose_hypothesis("Weak candidate")["node_id"]

    for _ in range(5):
        impl.update_bt_rating(a, b, source="llm_judge")
    for _ in range(5):
        impl.update_bt_rating(b, c, source="llm_judge")
    for _ in range(5):
        impl.update_bt_rating(a, c, source="llm_judge")

    board = impl.get_bt_leaderboard(top_k=5)
    ids = [row["node_id"] for row in board]
    assert ids[0] == a
    assert ids[-1] == c
    for row in board:
        assert row["lcb"] <= row["strength"] <= row["ucb"]
        assert row["interval_method"] == "laplace_map_centered_approximate_posterior"
        assert row["interval_kind"] == "laplace_credible"
        assert row["interval_calibrated"] is False
        assert row["probability_best"] is not None
        assert row["probability_best_calibrated"] is False
        assert row["fit_converged"] is True
        assert row["fit_comparison_count"] == 15
        assert row["insufficient_samples"] is False
    assert sum(row["probability_best"] for row in board) == pytest.approx(1.0)


def test_bt_fit_state_persists_full_covariance(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]
    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]

    result = impl.update_bt_rating(a, b, source="llm_judge")
    assert result["fit"]["converged"] is True
    assert result["fit"]["comparison_count"] == 1

    con = db._connect()
    try:
        row = con.execute(
            "SELECT * FROM mem_bt_fit_state WHERE kind = 'hypothesis'"
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    assert row["converged"] == 1
    assert row["comparison_count"] == 1
    assert row["iterations"] >= 1
    assert a in row["node_order_json"]
    assert b in row["node_order_json"]


def test_compare_bt_candidates_uses_joint_covariance(workspace):
    impl = workspace["memory_mcp.impl"]
    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]
    for _ in range(8):
        impl.update_bt_rating(a, b, source="llm_judge")

    contrast = impl.compare_bt_candidates(a, b)
    assert contrast["strength_difference_a_minus_b"] > 0
    assert contrast["difference_variance"] > 0
    assert contrast["probability_a_beats_b"] > 0.95
    assert contrast["credible_interval_95"][0] < contrast["credible_interval_95"][1]
    assert contrast["posterior_calibrated"] is False
    assert contrast["fit_converged"] is True


def test_bt_fit_failure_preserves_last_good_ratings(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]
    bt_module = __import__("memory_mcp.tools.bt", fromlist=["_fit_bt_arrays_with_state"])
    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]
    impl.update_bt_rating(a, b, source="llm_judge")
    before = {row["node_id"]: row["strength"] for row in impl.get_bt_leaderboard()}

    def fail_fit(*args, **kwargs):
        raise RuntimeError("synthetic non-convergence")

    monkeypatch.setattr(bt_module, "_fit_bt_arrays_with_state", fail_fit)
    result = impl.update_bt_rating(a, b, source="llm_judge")
    after = {row["node_id"]: row for row in impl.get_bt_leaderboard()}

    assert result["fit"]["converged"] is False
    assert result["fit"]["ratings_preserved"] is True
    assert {node_id: row["strength"] for node_id, row in after.items()} == before
    assert all(row["fit_converged"] is False for row in after.values())

    con = db._connect()
    try:
        comparison_count = con.execute(
            "SELECT COUNT(*) FROM mem_bt_comparisons"
        ).fetchone()[0]
        state = con.execute(
            "SELECT converged, comparison_count, fit_error FROM mem_bt_fit_state "
            "WHERE kind = 'hypothesis'"
        ).fetchone()
    finally:
        con.close()
    assert comparison_count == 2
    assert state["converged"] == 0
    assert state["comparison_count"] == 2
    assert "synthetic non-convergence" in state["fit_error"]


def test_batch_bt_fit_is_invariant_to_comparison_order(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]
    sequence = [(a, b)] * 10 + [(b, a)] * 10
    for winner, loser in sequence:
        impl.update_bt_rating(winner, loser, source="llm_judge")
    first = {row["node_id"]: row for row in impl.get_bt_leaderboard()}

    con = db._connect()
    try:
        con.execute("DELETE FROM mem_bt_comparisons")
        con.execute(
            "UPDATE mem_bt_ratings SET strength=0, strength_var=1, n_comparisons=0"
        )
    finally:
        con.close()

    for winner, loser in reversed(sequence):
        impl.update_bt_rating(winner, loser, source="llm_judge")
    second = {row["node_id"]: row for row in impl.get_bt_leaderboard()}

    for node_id in (a, b):
        assert second[node_id]["strength"] == pytest.approx(first[node_id]["strength"])
        assert second[node_id]["strength_var"] == pytest.approx(
            first[node_id]["strength_var"]
        )
    assert first[a]["strength"] == pytest.approx(0.0, abs=1e-9)
    assert first[b]["strength"] == pytest.approx(0.0, abs=1e-9)


def test_batch_bt_refit_updates_all_connected_nodes(workspace):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]
    c = impl.propose_hypothesis("C")["node_id"]
    impl.update_bt_rating(a, b, source="llm_judge")
    before = {row["node_id"]: row for row in impl.get_bt_leaderboard()}
    impl.update_bt_rating(b, c, source="llm_judge")
    after = {row["node_id"]: row for row in impl.get_bt_leaderboard()}

    assert after[a]["strength"] != pytest.approx(before[a]["strength"])
    assert after[a]["n_comparisons"] == 1
    assert after[b]["n_comparisons"] == 2
    assert after[c]["n_comparisons"] == 1


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), float("-inf"), 0, -1])
def test_update_bt_rating_rejects_non_finite_or_non_positive_weight(workspace, weight):
    impl = workspace["memory_mcp.impl"]
    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]
    with pytest.raises(ValueError, match="positive finite"):
        impl.update_bt_rating(a, b, source="llm_judge", weight=weight)


def test_update_bt_rating_rejects_unknown_source(workspace):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]

    try:
        impl.update_bt_rating(a, b, source="random_walk")
    except ValueError as exc:
        assert "source" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported source")


def test_update_bt_rating_rejects_self_match(workspace):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("A")["node_id"]

    try:
        impl.update_bt_rating(a, a, source="llm_judge")
    except ValueError:
        return
    raise AssertionError("expected ValueError for self-match")


def test_update_bt_rating_rejects_non_hypothesis_nodes(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    hypothesis_id = impl.propose_hypothesis("A")["node_id"]
    evidence_id = impl.attach_evidence(
        hypothesis_id,
        "supporting evidence",
        "supports",
    )["evidence_id"]

    try:
        impl.update_bt_rating(hypothesis_id, evidence_id, source="llm_judge")
    except ValueError as exc:
        assert "hypothesis" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-hypothesis BT comparison")

    con = db._connect()
    try:
        comparison_count = con.execute(
            "SELECT COUNT(*) FROM mem_bt_comparisons"
        ).fetchone()[0]
        evidence_bt_row = con.execute(
            "SELECT 1 FROM mem_bt_ratings WHERE node_id = ?",
            (evidence_id,),
        ).fetchone()
    finally:
        con.close()
    assert comparison_count == 0
    assert evidence_bt_row is None


def test_update_bt_rating_emits_cockpit_event(workspace):
    impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace.get("cockpit.data")
    if cockpit_data is None:
        return

    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]

    impl.update_bt_rating(a, b, source="llm_judge")

    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "bt_rating_updated" in kinds
    bt_event = next(event for event in events if event["kind"] == "bt_rating_updated")
    assert bt_event["payload"]["winner_id"] == a
    assert bt_event["payload"]["loser_id"] == b


def test_bt_strength_correlates_with_win_rate_better_than_elo(workspace):
    impl = workspace["memory_mcp.impl"]

    nodes = [impl.propose_hypothesis(f"Hypothesis {i}")["node_id"] for i in range(4)]

    fixtures = [
        (nodes[0], nodes[1], nodes[0]),
        (nodes[0], nodes[2], nodes[0]),
        (nodes[0], nodes[3], nodes[0]),
        (nodes[1], nodes[2], nodes[1]),
        (nodes[1], nodes[3], nodes[1]),
        (nodes[2], nodes[3], nodes[2]),
    ]
    for a, b, w in fixtures:
        impl.record_judgement(a, b, w, reason="tournament")

    board = impl.get_bt_leaderboard(top_k=10)
    by_id = {row["node_id"]: row for row in board}
    strengths = [by_id[node]["strength"] for node in nodes]
    # Strict descending order of strengths
    for prev, cur in zip(strengths, strengths[1:]):
        assert prev > cur
    # First node should also dominate in elo
    assert by_id[nodes[0]]["elo_score"] > by_id[nodes[-1]]["elo_score"]
    # Variance should drop as comparisons accumulate
    assert all(row["strength_var"] < 1.0 for row in board)
    # Sanity: confidence intervals make sense
    assert math.isclose(by_id[nodes[0]]["strength"], strengths[0], rel_tol=1e-6)
