"""End-to-end realtime pruning smoke (V3.0 P3).

Two trips through suggest_pause_low_strength:
1. Default (dry-run) emits ``branch_pause_suggested`` only.
2. With ``RESEARCH_AGENT_AUTO_PRUNE=1`` it additionally flips status to
   ``paused`` and emits ``branch_paused``.
"""

from __future__ import annotations


def _drive_round_robin(impl, winner: str, loser: str, rounds: int = 12) -> None:
    for _ in range(rounds):
        impl.update_bt_rating(winner, loser, source="llm_judge")


def test_realtime_prune_dry_run_then_auto(workspace, monkeypatch):
    memory_impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace["cockpit.data"]

    a = memory_impl.propose_hypothesis("Strong arm")["node_id"]
    b = memory_impl.propose_hypothesis("Weak arm")["node_id"]
    _drive_round_robin(memory_impl, a, b)

    monkeypatch.delenv("RESEARCH_AGENT_AUTO_PRUNE", raising=False)
    dry = memory_impl.suggest_pause_low_strength(
        ucb_threshold=0.0, min_comparisons=4
    )
    assert dry["auto_prune"] is False
    assert any(row["node_id"] == b for row in dry["suggested"])
    assert dry["paused"] == []

    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "branch_pause_suggested" in kinds
    assert "branch_paused" not in kinds

    monkeypatch.setenv("RESEARCH_AGENT_AUTO_PRUNE", "1")
    auto = memory_impl.suggest_pause_low_strength(
        ucb_threshold=0.0, min_comparisons=4
    )
    assert auto["auto_prune"] is True
    assert any(row["node_id"] == b for row in auto["paused"])

    later_events = cockpit_data.fetch_new_events(0)
    assert "branch_paused" in [event["kind"] for event in later_events]

    board = memory_impl.get_bt_leaderboard(top_k=5)
    paused_ids = {row["node_id"] for row in board if row["status"] == "paused"}
    assert b not in paused_ids  # excluded by default
    full_board = memory_impl.get_bt_leaderboard(top_k=5, include_paused=True)
    by_id = {row["node_id"]: row for row in full_board}
    assert by_id[b]["status"] == "paused"

    resumed = memory_impl.resume_branch(b, reason="restored by test")
    assert resumed["previous_status"] == "paused"
    assert resumed["status"] == "active"
