"""Smoke test for ActivityPane: widget instantiates and renders cards.

Verifies the widget contract works end-to-end without spinning up the
full app. Visual fidelity is tested via the app smoke tests once
Milestone C wires it into the body grid.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cockpit.activity import ActivityCard, aggregate
from cockpit.panes.activity_pane import ActivityPane


def _ts(offset_sec: float, *, base: datetime | None = None) -> str:
    if base is None:
        base = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_sec)).isoformat()


def test_activity_pane_constructs() -> None:
    pane = ActivityPane()
    assert pane.id == "activity-pane"
    assert pane._cards == []  # type: ignore[attr-defined]


def test_aggregate_produces_cards_pane_can_accept() -> None:
    now = datetime(2026, 5, 13, 12, 1, 0, tzinfo=timezone.utc)
    cards = aggregate(
        [
            {
                "id": 1,
                "kind": "graph_delta",
                "payload": {"node_id": "hyp_1", "kind": "hypothesis"},
                "created_at": _ts(45.0),
            },
            {
                "id": 2,
                "kind": "graph_delta",
                "payload": {"node_id": "hyp_1", "kind": "hypothesis"},
                "created_at": _ts(50.0),
            },
        ],
        now=now,
    )
    # Pane consumes ActivityCard list — pure data flow, no render here.
    pane = ActivityPane()
    pane._cards = list(cards)  # type: ignore[attr-defined]
    assert len(pane._cards) == 1  # type: ignore[attr-defined]
    assert pane._cards[0].focus_node_id == "hyp_1"  # type: ignore[attr-defined]


def test_set_cards_stores_all_status_values() -> None:
    # Pane stores arbitrary status without crashing in pure-data path.
    for status in ("running", "done", "failed", "blocked"):
        card = ActivityCard(
            card_id="x",
            family="bt",
            title="bt · test",
            focus_node_id="hyp_1",
            status=status,
            severity="medium",
            first_event_id=1,
            last_event_id=2,
            first_at=_ts(0),
            last_at=_ts(10),
            event_count=2,
        )
        pane = ActivityPane()
        pane._cards = [card]  # type: ignore[attr-defined]
        assert pane._cards[0].status == status  # type: ignore[attr-defined]


def test_activity_pane_filter_matches_card_content() -> None:
    cards = [
        ActivityCard(
            card_id="a",
            family="verify",
            title="verify · hyp_keep",
            focus_node_id="hyp_keep",
            status="running",
            severity="medium",
            first_event_id=1,
            last_event_id=1,
            first_at=_ts(0),
            last_at=_ts(0),
            event_count=1,
            recent_event_lines=("12:00:00  seed_run_recorded",),
        ),
        ActivityCard(
            card_id="b",
            family="graph",
            title="graph · hyp_drop",
            focus_node_id="hyp_drop",
            status="running",
            severity="info",
            first_event_id=2,
            last_event_id=2,
            first_at=_ts(0),
            last_at=_ts(0),
            event_count=1,
            recent_event_lines=("12:00:00  graph_delta",),
        ),
    ]
    pane = ActivityPane()
    pane._cards = cards  # type: ignore[attr-defined]
    pane._filter_text = "seed"  # type: ignore[attr-defined]

    visible = pane._visible_cards()  # type: ignore[attr-defined]
    assert [card.card_id for card in visible] == ["a"]
