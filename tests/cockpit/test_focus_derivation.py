"""Unit tests for cockpit.panes.focus_pane.derive_focus — pure function."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cockpit.panes.focus_pane import FocusState, derive_focus


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


def test_empty_events_returns_empty_focus() -> None:
    state = derive_focus([], now=_NOW)
    assert state.nodes == ()
    assert state.scores == {}
    assert state.confidence == 0.0


def test_single_node_dominates() -> None:
    state = derive_focus(
        [
            _ev(1, "graph_delta", t=55.0, payload={"node_id": "hyp_01"}),
            _ev(2, "graph_delta", t=58.0, payload={"node_id": "hyp_01"}),
            _ev(3, "graph_delta", t=59.0, payload={"node_id": "hyp_01"}),
        ],
        now=_NOW,
    )
    assert state.nodes == ("hyp_01",)
    assert not state.is_divided


def test_divided_focus_when_scores_close() -> None:
    state = derive_focus(
        [
            _ev(1, "graph_delta", t=55.0, payload={"node_id": "hyp_01"}),
            _ev(2, "graph_delta", t=56.0, payload={"node_id": "hyp_02"}),
            _ev(3, "graph_delta", t=57.0, payload={"node_id": "hyp_03"}),
        ],
        now=_NOW,
    )
    # Three events with nearly equal scores — divided focus.
    assert state.is_divided
    assert set(state.nodes) >= {"hyp_01", "hyp_02", "hyp_03"}


def test_phase_set_focus_nodes_take_priority() -> None:
    state = derive_focus(
        [
            _ev(1, "graph_delta", t=55.0, payload={"node_id": "hyp_zzz"}),
            _ev(
                2,
                "phase_set",
                t=58.0,
                payload={
                    "phase": "prove",
                    "focus_nodes": ["prop_42"],
                    "intent": "Drafting NL proof",
                },
            ),
        ],
        now=_NOW,
    )
    # Explicit focus_nodes from phase_set should appear first.
    assert state.nodes[0] == "prop_42"
    assert state.intent == "Drafting NL proof"


def test_cooldown_keeps_prev_top_when_new_top_marginal() -> None:
    prev = FocusState(
        nodes=("hyp_old",),
        scores={"hyp_old": 5.0},
        confidence=1.0,
    )
    # New events give hyp_new a slightly higher score but not 20% higher.
    state = derive_focus(
        [
            _ev(1, "graph_delta", t=55.0, payload={"node_id": "hyp_old"}),
            _ev(2, "graph_delta", t=56.0, payload={"node_id": "hyp_old"}),
            _ev(3, "graph_delta", t=58.0, payload={"node_id": "hyp_new"}),
            _ev(4, "graph_delta", t=59.0, payload={"node_id": "hyp_new"}),
        ],
        now=_NOW,
        prev=prev,
    )
    # Should keep hyp_old in the lead due to cooldown.
    assert state.nodes[0] == "hyp_old"


def test_cooldown_allows_dominant_new_top() -> None:
    prev = FocusState(nodes=("hyp_old",), scores={"hyp_old": 1.0}, confidence=1.0)
    state = derive_focus(
        [
            _ev(1, "graph_delta", t=58.0, payload={"node_id": "hyp_new"}),
            _ev(2, "graph_delta", t=59.0, payload={"node_id": "hyp_new"}),
            _ev(3, "graph_delta", t=59.5, payload={"node_id": "hyp_new"}),
        ],
        now=_NOW,
        prev=prev,
    )
    # hyp_new dominates — should swap in even with cooldown.
    assert state.nodes[0] == "hyp_new"


def test_old_events_excluded_by_window() -> None:
    state = derive_focus(
        [
            _ev(1, "graph_delta", t=-3600.0, payload={"node_id": "hyp_ancient"}),
            _ev(2, "graph_delta", t=-1800.0, payload={"node_id": "hyp_ancient"}),
        ],
        now=_NOW,
        window_seconds=120,
    )
    assert state.nodes == ()


def test_judgement_winner_outweighs_loser() -> None:
    state = derive_focus(
        [
            _ev(
                1,
                "judgement_recorded",
                t=55.0,
                payload={
                    "winner_node_id": "hyp_winner",
                    "a_node_id": "hyp_loser_a",
                    "b_node_id": "hyp_loser_b",
                },
            ),
            _ev(
                2,
                "judgement_recorded",
                t=58.0,
                payload={
                    "winner_node_id": "hyp_winner",
                    "a_node_id": "hyp_winner",
                    "b_node_id": "hyp_loser_b",
                },
            ),
        ],
        now=_NOW,
    )
    assert state.nodes[0] == "hyp_winner"


def test_agent_narration_with_node_scope_contributes() -> None:
    state = derive_focus(
        [
            _ev(
                1,
                "agent_narration",
                t=55.0,
                payload={"text": "drafting", "scope": "node:hyp_42"},
            ),
        ],
        now=_NOW,
    )
    # Single event — not strong, but should still register.
    assert "hyp_42" in state.scores
    assert state.intent == "drafting"


def test_intent_only_set_once_per_state() -> None:
    state = derive_focus(
        [
            _ev(
                1,
                "phase_set",
                t=55.0,
                payload={
                    "phase": "prove",
                    "focus_nodes": ["prop_1"],
                    "intent": "primary intent",
                },
            ),
            _ev(
                2,
                "phase_set",
                t=58.0,
                payload={
                    "phase": "prove",
                    "focus_nodes": ["prop_1"],
                    "intent": "newer intent",
                },
            ),
        ],
        now=_NOW,
    )
    # Latest phase_set's intent wins (loop sets intent unconditionally on
    # each phase_set encountered).
    assert state.intent == "newer intent"
