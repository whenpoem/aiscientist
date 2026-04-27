"""End-to-end smoke for the V3.0 Bradley-Terry leaderboard.

Asserts that propose -> record_judgement (multiple rounds) -> get_bt_leaderboard
yields a stable ranking and pushes ``bt_rating_updated`` events into the cockpit
event stream so the TUI can react in near-real-time.
"""

from __future__ import annotations


def test_bt_round_robin_smoke(workspace):
    impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace.get("cockpit.data")

    a = impl.propose_hypothesis("A: dropout schedule beats fixed dropout")["node_id"]
    b = impl.propose_hypothesis("B: curriculum ordering matters")["node_id"]
    c = impl.propose_hypothesis("C: only batch size matters")["node_id"]

    # 12 record_judgements, A beats both, B beats C.
    fixtures = [
        (a, b, a),
        (a, c, a),
        (b, c, b),
        (a, b, a),
        (a, c, a),
        (b, c, b),
        (a, b, a),
        (a, c, a),
        (b, c, b),
        (a, b, a),
        (a, c, a),
        (b, c, b),
    ]
    for left, right, winner in fixtures:
        impl.record_judgement(left, right, winner, reason="smoke-tournament")

    board = impl.get_bt_leaderboard(top_k=10)
    ids = [row["node_id"] for row in board]
    assert ids[0] == a
    assert ids[-1] == c
    by_id = {row["node_id"]: row for row in board}
    assert by_id[a]["strength"] > by_id[b]["strength"] > by_id[c]["strength"]
    assert all(row["lcb"] <= row["strength"] <= row["ucb"] for row in board)
    assert all(row["n_comparisons"] >= 4 for row in board)

    if cockpit_data is not None:
        events = cockpit_data.fetch_new_events(0)
        bt_events = [event for event in events if event["kind"] == "bt_rating_updated"]
        # 12 record_judgements -> 12 bt_rating_updated events.
        assert len(bt_events) == 12
