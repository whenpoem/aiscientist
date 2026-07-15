from __future__ import annotations

import os


def _drive_loser(impl, winner: str, loser: str, n: int = 12) -> None:
    for _ in range(n):
        impl.update_bt_rating(winner, loser, source="llm_judge")


def test_suggest_pause_dry_run_does_not_change_status(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]
    monkeypatch.delenv("RESEARCH_AGENT_AUTO_PRUNE", raising=False)

    a = impl.propose_hypothesis("Strong A")["node_id"]
    b = impl.propose_hypothesis("Weak B")["node_id"]
    _drive_loser(impl, a, b)

    result = impl.suggest_pause_low_strength(ucb_threshold=0.0, min_comparisons=4)
    assert result["auto_prune"] is False
    suggested = {row["node_id"] for row in result["suggested"]}
    assert b in suggested
    assert result["paused"] == []

    board = impl.get_bt_leaderboard(top_k=10)
    by_id = {row["node_id"]: row for row in board}
    assert by_id[b]["status"] == "active"


def test_legacy_strength_suggestion_ignores_auto_prune_env(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]
    monkeypatch.setenv("RESEARCH_AGENT_AUTO_PRUNE", "1")

    a = impl.propose_hypothesis("Strong A")["node_id"]
    b = impl.propose_hypothesis("Weak B")["node_id"]
    _drive_loser(impl, a, b)

    result = impl.suggest_pause_low_strength(ucb_threshold=0.0, min_comparisons=4)
    assert result["auto_prune"] is False
    assert result["deprecated"] is True
    assert result["paused"] == []

    board = impl.get_bt_leaderboard(top_k=10)
    by_id = {row["node_id"]: row for row in board}
    assert by_id[b]["status"] == "active"


def test_suggest_pause_respects_min_comparisons(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]
    monkeypatch.delenv("RESEARCH_AGENT_AUTO_PRUNE", raising=False)

    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]
    impl.update_bt_rating(a, b, source="llm_judge")

    # Only 1 comparison; min_comparisons=6 should suppress.
    result = impl.suggest_pause_low_strength(ucb_threshold=10.0, min_comparisons=6)
    assert result["suggested"] == []


def test_resume_branch_restores_active(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]
    monkeypatch.setenv("RESEARCH_AGENT_AUTO_PRUNE", "1")

    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]
    _drive_loser(impl, a, b)
    impl.suggest_pause_low_probability(
        max_probability_best=0.25,
        min_comparisons=4,
    )

    result = impl.resume_branch(b, reason="user override")
    assert result["status"] == "active"
    assert result["previous_status"] == "paused"

    board = impl.get_bt_leaderboard(top_k=10)
    by_id = {row["node_id"]: row for row in board}
    assert by_id[b]["status"] == "active"


def test_resume_branch_no_op_when_already_active(workspace):
    impl = workspace["memory_mcp.impl"]
    a = impl.propose_hypothesis("A")["node_id"]
    result = impl.resume_branch(a, reason="just because")
    assert result["status"] == "active"
    assert result["previous_status"] == "active"


def test_eig_prefers_high_variance_underdog(workspace):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("Confident leader A")["node_id"]
    b = impl.propose_hypothesis("Mid B")["node_id"]
    c = impl.propose_hypothesis("Untested C")["node_id"]

    for _ in range(12):
        impl.update_bt_rating(a, b, source="llm_judge")

    scores = impl.expected_information_gain([b, c])
    by_id = {row["node_id"]: row for row in scores}
    # C has high variance (never compared) so its EIG should dominate B's.
    assert by_id[c]["expected_information_gain"] >= by_id[b]["expected_information_gain"]
    assert by_id[c]["ref_node_id"] == a
    assert scores[0]["node_id"] == c


def test_pause_suggestions_emit_cockpit_events(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace.get("cockpit.data")
    if cockpit_data is None:
        return
    monkeypatch.delenv("RESEARCH_AGENT_AUTO_PRUNE", raising=False)

    a = impl.propose_hypothesis("Strong")["node_id"]
    b = impl.propose_hypothesis("Weak")["node_id"]
    _drive_loser(impl, a, b)

    impl.suggest_pause_low_strength(ucb_threshold=0.0, min_comparisons=4)
    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "branch_pause_suggested" in kinds
    assert "branch_paused" not in kinds  # dry-run by default


def test_auto_prune_env_variations(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("A")["node_id"]
    b = impl.propose_hypothesis("B")["node_id"]
    _drive_loser(impl, a, b)

    for falsy in ("", "0", "false", "False"):
        monkeypatch.setenv("RESEARCH_AGENT_AUTO_PRUNE", falsy)
        result = impl.suggest_pause_low_probability(
            max_probability_best=0.25, min_comparisons=4
        )
        assert result["auto_prune"] is False, f"unexpected truthy for {falsy!r}"

    for truthy in ("1", "true", "yes"):
        monkeypatch.setenv("RESEARCH_AGENT_AUTO_PRUNE", truthy)
        result = impl.suggest_pause_low_probability(
            max_probability_best=0.25, min_comparisons=4
        )
        assert result["auto_prune"] is True, f"unexpected falsy for {truthy!r}"
        # Restore so the next iteration starts from active again.
        impl.resume_branch(b, reason="reset")

    monkeypatch.delenv("RESEARCH_AGENT_AUTO_PRUNE", raising=False)
    assert os.environ.get("RESEARCH_AGENT_AUTO_PRUNE") is None


def test_probability_pause_is_dry_run_by_default(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]
    monkeypatch.delenv("RESEARCH_AGENT_AUTO_PRUNE", raising=False)

    a = impl.propose_hypothesis("Dominant A")["node_id"]
    b = impl.propose_hypothesis("Weak B")["node_id"]
    _drive_loser(impl, a, b)

    result = impl.suggest_pause_low_probability(
        max_probability_best=0.25,
        min_comparisons=4,
    )
    assert result["auto_prune"] is False
    assert any(row["node_id"] == b for row in result["suggested"])
    assert result["paused"] == []


def test_probability_pause_with_env_actually_pauses(workspace, monkeypatch):
    impl = workspace["memory_mcp.impl"]
    monkeypatch.setenv("RESEARCH_AGENT_AUTO_PRUNE", "1")

    a = impl.propose_hypothesis("Dominant A")["node_id"]
    b = impl.propose_hypothesis("Weak B")["node_id"]
    _drive_loser(impl, a, b)

    result = impl.suggest_pause_low_probability(
        max_probability_best=0.25,
        min_comparisons=4,
    )
    assert any(row["node_id"] == b for row in result["paused"])
    full = impl.get_bt_leaderboard(top_k=10, include_paused=True)
    assert {row["node_id"]: row["status"] for row in full}[b] == "paused"
