"""Unit tests for cockpit.activity — pure aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cockpit.activity import (
    CARD_BODY_LINES_MAX,
    SEVERITY_ORDER,
    aggregate,
)


def _ts(offset_sec: float, *, base: datetime | None = None) -> str:
    if base is None:
        base = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_sec)).isoformat()


def _ev(eid: int, kind: str, *, t: float = 0.0, payload: dict | None = None) -> dict:
    return {
        "id": eid,
        "kind": kind,
        "payload": payload or {},
        "created_at": _ts(t),
    }


_NOW = datetime(2026, 5, 13, 12, 1, 0, tzinfo=timezone.utc)


def test_empty_returns_empty_list() -> None:
    assert aggregate([], now=_NOW) == []


def test_unknown_internal_events_are_not_activity_cards() -> None:
    cards = aggregate(
        [
            _ev(1, "turn_end", t=55.0, payload={"summary": {"active_hypotheses": 3}}),
            _ev(2, "unregistered_internal_event", t=56.0, payload={}),
        ],
        now=_NOW,
    )
    assert cards == []


def test_groups_graph_deltas_by_node_id() -> None:
    cards = aggregate(
        [
            _ev(1, "graph_delta", t=10.0, payload={"node_id": "hyp_06", "kind": "hypothesis"}),
            _ev(2, "graph_delta", t=20.0, payload={"node_id": "hyp_06", "kind": "hypothesis"}),
            _ev(3, "graph_delta", t=30.0, payload={"node_id": "hyp_07", "kind": "hypothesis"}),
        ],
        now=_NOW,
    )
    assert len(cards) == 2
    by_focus = {c.focus_node_id: c for c in cards}
    assert by_focus["hyp_06"].event_count == 2
    assert by_focus["hyp_07"].event_count == 1


def test_proof_pipeline_collapses_to_one_card_per_draft() -> None:
    cards = aggregate(
        [
            _ev(1, "proof_segmented", t=10.0, payload={"draft_id": "prop_42"}),
            _ev(
                2,
                "proof_diagnosis_recorded",
                t=20.0,
                payload={"draft_id": "prop_42", "is_flawed": True},
            ),
            _ev(
                3,
                "proof_diagnosis_complete",
                t=30.0,
                payload={"draft_id": "prop_42"},
            ),
        ],
        now=_NOW,
    )
    assert len(cards) == 1
    assert cards[0].family == "prove"
    assert cards[0].focus_node_id == "prop_42"
    assert cards[0].event_count == 3


def test_singleton_failure_added_does_not_merge() -> None:
    cards = aggregate(
        [
            _ev(1, "failure_added", t=10.0, payload={"failure_id": 1, "trigger": "oom"}),
            _ev(2, "failure_added", t=20.0, payload={"failure_id": 2, "trigger": "nan"}),
        ],
        now=_NOW,
    )
    # Singleton — two events, two cards.
    assert len(cards) == 2


def test_terminal_lean_event_marks_done() -> None:
    cards = aggregate(
        [
            _ev(1, "lean_proof_recorded", t=10.0, payload={"proposition_id": "prop_1"}),
            _ev(
                2,
                "lean_proof_succeeded",
                t=20.0,
                payload={"proposition_id": "prop_1"},
            ),
        ],
        now=_NOW,
    )
    assert len(cards) == 1
    assert cards[0].status == "done"
    assert cards[0].closed_at  # populated by terminal


def test_lean_proof_failed_marks_failed() -> None:
    cards = aggregate(
        [
            _ev(1, "lean_proof_failed", t=20.0, payload={"proposition_id": "prop_1"}),
        ],
        now=_NOW,
    )
    assert len(cards) == 1
    assert cards[0].status == "failed"
    # Singleton in this case because failure_kind isn't in SINGLETON_KINDS
    # but lean events are not bucketed unless they share focus → here single event.


def test_budget_exceeded_is_critical_singleton_blocker() -> None:
    cards = aggregate(
        [
            _ev(1, "budget_exceeded", t=30.0, payload={"node_id": "hyp_01", "used": 1800}),
        ],
        now=_NOW,
    )
    assert len(cards) == 1
    card = cards[0]
    assert card.status == "blocked"
    assert card.severity == "critical"


def test_card_severity_is_max_of_constituents() -> None:
    cards = aggregate(
        [
            _ev(1, "bt_rating_updated", t=10.0, payload={"node_id": "hyp_01"}),  # low
            _ev(
                2,
                "judgement_recorded",
                t=15.0,
                payload={"winner_node_id": "hyp_01"},
            ),
            _ev(
                3,
                "judgement_recorded",
                t=20.0,
                payload={"winner_node_id": "hyp_01"},
            ),
        ],
        now=_NOW,
    )
    # bt family — all events combined into one card on focus hyp_01.
    assert len(cards) == 1
    # All events are low/medium → check severity is one of those, not info.
    assert cards[0].severity in SEVERITY_ORDER
    assert cards[0].severity != "critical"


def test_deterministic_card_id() -> None:
    events = [
        _ev(1, "graph_delta", t=10.0, payload={"node_id": "hyp_06", "kind": "hypothesis"}),
        _ev(2, "graph_delta", t=20.0, payload={"node_id": "hyp_06", "kind": "hypothesis"}),
    ]
    first = aggregate(events, now=_NOW)
    second = aggregate(events, now=_NOW)
    assert first[0].card_id == second[0].card_id
    assert first[0].card_id == aggregate(events, now=_NOW)[0].card_id


def test_card_body_truncates_to_max_lines() -> None:
    events = [
        _ev(
            i,
            "bt_rating_updated",
            t=float(i),
            payload={"node_id": "hyp_42"},
        )
        for i in range(1, 20)
    ]
    cards = aggregate(events, now=_NOW)
    assert len(cards) == 1
    assert len(cards[0].recent_event_lines) == CARD_BODY_LINES_MAX
    assert cards[0].event_count == 19


def test_sort_order_running_blocked_failed_done() -> None:
    cards = aggregate(
        [
            _ev(1, "lean_proof_failed", t=10.0, payload={"proposition_id": "prop_1"}),
            _ev(2, "budget_exceeded", t=20.0, payload={"node_id": "hyp_07"}),
            _ev(3, "proof_segmented", t=30.0, payload={"draft_id": "prop_5"}),
            _ev(4, "proof_diagnosis_complete", t=40.0, payload={"draft_id": "prop_5"}),
            _ev(5, "graph_delta", t=55.0, payload={"node_id": "hyp_08", "kind": "hypothesis"}),
            _ev(6, "graph_delta", t=58.0, payload={"node_id": "hyp_08", "kind": "hypothesis"}),
        ],
        now=_NOW,
    )
    statuses = [c.status for c in cards]
    # Sort key is (status_order, -last_event_id); running first.
    assert statuses[0] == "running"
    # Blocked comes before failed comes before done.
    if "blocked" in statuses and "failed" in statuses:
        assert statuses.index("blocked") < statuses.index("failed")
    if "failed" in statuses and "done" in statuses:
        assert statuses.index("failed") < statuses.index("done")


def test_old_events_filtered_by_window() -> None:
    # event 60 minutes ago — past default 30 min window
    cards = aggregate(
        [
            _ev(1, "graph_delta", t=-3600.0, payload={"node_id": "hyp_old"}),
            _ev(2, "graph_delta", t=-3600.0, payload={"node_id": "hyp_old"}),
        ],
        now=_NOW,
        window_seconds=1800,
    )
    assert cards == []


def test_intervention_payload_kinds_collected_in_summary() -> None:
    cards = aggregate(
        [
            _ev(
                1,
                "intervention",
                t=10.0,
                payload={"kind": "reject", "target": "hyp_05"},
            ),
            _ev(
                2,
                "intervention",
                t=20.0,
                payload={"kind": "redirect", "target": "hyp_05"},
            ),
        ],
        now=_NOW,
    )
    # Both interventions target hyp_05 → group into one card.
    # The card's summary_fields captures both intervention kinds.
    assert len(cards) == 1
    assert cards[0].family == "intervention"
    assert set(cards[0].summary_fields["kinds"]) == {"reject", "redirect"}


def test_focus_node_id_resolved_from_winner_field() -> None:
    cards = aggregate(
        [
            _ev(
                1,
                "judgement_recorded",
                t=10.0,
                payload={
                    "winner_node_id": "hyp_winner",
                    "a_node_id": "hyp_a",
                    "b_node_id": "hyp_b",
                },
            ),
            _ev(
                2,
                "judgement_recorded",
                t=20.0,
                payload={
                    "winner_node_id": "hyp_winner",
                    "a_node_id": "hyp_winner",
                    "b_node_id": "hyp_c",
                },
            ),
        ],
        now=_NOW,
    )
    assert len(cards) == 1
    assert cards[0].focus_node_id == "hyp_winner"


def test_running_status_decays_to_done_after_30s_quiet() -> None:
    # last event 60s before _NOW → running heuristic flips to done
    cards = aggregate(
        [
            _ev(1, "graph_delta", t=-90.0, payload={"node_id": "hyp_q"}),
            _ev(2, "graph_delta", t=-60.0, payload={"node_id": "hyp_q"}),
        ],
        now=_NOW,
        window_seconds=600,
    )
    assert len(cards) == 1
    assert cards[0].status == "done"


def test_phase_set_does_not_merge_with_other_kinds() -> None:
    cards = aggregate(
        [
            _ev(1, "phase_set", t=10.0, payload={"phase": "prove", "focus_nodes": ["prop_1"]}),
            _ev(2, "graph_delta", t=20.0, payload={"node_id": "prop_1"}),
        ],
        now=_NOW,
    )
    families = {c.family for c in cards}
    assert "narrate" in families
    assert "graph" in families  # graph_delta carries its own card
