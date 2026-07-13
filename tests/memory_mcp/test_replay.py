from __future__ import annotations


def test_replay_does_not_pollute_main_graph(workspace):
    impl = workspace["memory_mcp.impl"]

    a = impl.propose_hypothesis("Hypothesis A")["node_id"]
    b = impl.propose_hypothesis("Hypothesis B")["node_id"]
    impl.update_bt_rating(a, b, source="llm_judge")

    snap = impl.snapshot(label="before-counterfactual")

    branch = impl.replay_counterfactual(
        snapshot_id=snap["snapshot_id"],
        counterfactual=f"Approve {b} instead of pruning it",
    )
    assert branch["branch_id"].startswith("replay_")
    assert branch["snapshot_id"] == snap["snapshot_id"]
    assert branch["divergence"]["counterfactual"].startswith("Approve")

    # Main graph state unchanged: leaderboard still shows A on top.
    board = impl.get_bt_leaderboard(top_k=2)
    assert board[0]["node_id"] == a


def test_replay_unknown_snapshot_raises(workspace):
    impl = workspace["memory_mcp.impl"]
    raised = False
    try:
        impl.replay_counterfactual(snapshot_id="snap_missing", counterfactual="anything")
    except ValueError:
        raised = True
    assert raised


def test_list_snapshots_returns_metadata_newest_first(workspace):
    impl = workspace["memory_mcp.impl"]
    first = impl.snapshot(label="first")
    second = impl.snapshot(label="second")

    rows = impl.list_snapshots(limit=20)
    assert [row["snapshot_id"] for row in rows[:2]] == [
        second["snapshot_id"],
        first["snapshot_id"],
    ]
    assert rows[0]["label"] == "second"
    assert isinstance(rows[0]["counts"], dict)
    assert "nodes" in rows[0]["counts"]


def test_replay_empty_counterfactual_rejected(workspace):
    impl = workspace["memory_mcp.impl"]
    snap = impl.snapshot(label="empty-test")
    raised = False
    try:
        impl.replay_counterfactual(snapshot_id=snap["snapshot_id"], counterfactual="   ")
    except ValueError:
        raised = True
    assert raised


def test_list_replay_branches_orders_newest_first(workspace):
    impl = workspace["memory_mcp.impl"]
    snap = impl.snapshot(label="ordering-test")

    first = impl.replay_counterfactual(snap["snapshot_id"], "first")
    second = impl.replay_counterfactual(snap["snapshot_id"], "second")
    third = impl.replay_counterfactual(snap["snapshot_id"], "third")

    listing = impl.list_replay_branches(limit=10)
    branch_ids = [row["branch_id"] for row in listing]
    assert branch_ids[0] == third["branch_id"]
    assert first["branch_id"] in branch_ids
    assert second["branch_id"] in branch_ids


def test_replay_emits_cockpit_event(workspace):
    impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace.get("cockpit.data")
    if cockpit_data is None:
        return
    snap = impl.snapshot(label="event-test")
    impl.replay_counterfactual(snap["snapshot_id"], "imagine the user approved hyp_x")
    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "replay_branch_created" in kinds
