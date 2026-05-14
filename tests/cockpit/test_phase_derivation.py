"""Unit tests for cockpit.phase — pure function, deterministic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cockpit import phase as phase_mod
from cockpit.phase import PHASES, Phase, derive_phase


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


def test_empty_events_returns_idle() -> None:
    p = derive_phase([], now=_NOW)
    assert p.name == "idle"
    assert p.confidence == 0.0
    assert p.last_event_id == 0


def test_idle_when_newest_event_older_than_threshold() -> None:
    # event is 120s old, idle threshold default 90s
    p = derive_phase(
        [_ev(1, "graph_delta", t=-60.0), _ev(2, "graph_delta", t=0.0)],
        now=_NOW,
        idle_threshold_sec=10,  # set threshold to 10s so 60s-old looks idle
    )
    assert p.name == "idle"


def test_single_event_stays_idle_anti_flicker() -> None:
    # one graph_delta inside threshold — anti-flicker requires 2 events
    p = derive_phase([_ev(1, "graph_delta", t=55.0)], now=_NOW)
    assert p.name == "idle"


def test_two_graph_deltas_classify_explore() -> None:
    p = derive_phase(
        [_ev(1, "graph_delta", t=50.0), _ev(2, "graph_delta", t=55.0)],
        now=_NOW,
    )
    assert p.name == "explore"
    assert p.confidence > 0
    assert "graph_delta" in p.source_kinds


def test_bt_signals_classify_select() -> None:
    p = derive_phase(
        [
            _ev(1, "judgement_recorded", t=40.0),
            _ev(2, "bt_rating_updated", t=45.0),
            _ev(3, "bt_rating_updated", t=55.0),
        ],
        now=_NOW,
    )
    assert p.name == "select"


def test_lean_attempt_classifies_prove() -> None:
    p = derive_phase(
        [
            _ev(1, "proof_segmented", t=30.0),
            _ev(2, "lean_proof_recorded", t=50.0),
        ],
        now=_NOW,
    )
    assert p.name == "prove"


def test_verify_kinds_classify_verify() -> None:
    p = derive_phase(
        [
            _ev(1, "prereg_locked", t=30.0),
            _ev(2, "seed_run_recorded", t=50.0),
        ],
        now=_NOW,
    )
    assert p.name == "verify"


def test_review_kinds_classify_review() -> None:
    p = derive_phase(
        [
            _ev(1, "claim_pinned", t=30.0),
            _ev(2, "snapshot_created", t=50.0),
        ],
        now=_NOW,
    )
    assert p.name == "review"


def test_explicit_phase_set_overrides_derivation() -> None:
    p = derive_phase(
        [
            _ev(1, "graph_delta", t=30.0),  # would suggest explore
            _ev(2, "graph_delta", t=40.0),
            _ev(
                3,
                "phase_set",
                t=50.0,
                payload={
                    "phase": "prove",
                    "focus_nodes": ["prop_01"],
                    "intent": "Drafting NL proof",
                },
            ),
        ],
        now=_NOW,
    )
    assert p.name == "prove"
    assert "prop_01" in p.focus_nodes
    assert p.intent == "Drafting NL proof"


def test_explicit_phase_set_with_invalid_name_falls_through_to_derivation() -> None:
    p = derive_phase(
        [
            _ev(1, "graph_delta", t=40.0),
            _ev(2, "graph_delta", t=50.0),
            _ev(3, "phase_set", t=55.0, payload={"phase": "bogus"}),
        ],
        now=_NOW,
    )
    assert p.name == "explore"  # falls back to majority


def test_tie_break_prefers_most_recent() -> None:
    # 2 explore + 2 select; the latest is select → select wins on tie
    p = derive_phase(
        [
            _ev(1, "graph_delta", t=30.0),
            _ev(2, "judgement_recorded", t=35.0),
            _ev(3, "graph_delta", t=40.0),
            _ev(4, "bt_rating_updated", t=50.0),  # latest contribution
        ],
        now=_NOW,
    )
    assert p.name == "select"


def test_confidence_is_majority_share() -> None:
    p = derive_phase(
        [
            _ev(1, "graph_delta", t=30.0),
            _ev(2, "graph_delta", t=35.0),
            _ev(3, "graph_delta", t=40.0),
            _ev(4, "judgement_recorded", t=50.0),
        ],
        now=_NOW,
    )
    assert p.name == "explore"
    assert p.confidence == pytest.approx(3 / 4)


def test_phase_names_match_constants() -> None:
    assert set(PHASES) == {
        "idle",
        "explore",
        "select",
        "experiment",
        "verify",
        "prove",
        "review",
        "narrate",
    }


def test_phase_glyph_and_color_token_coverage() -> None:
    # Every PHASES entry must have a glyph + color token, else the
    # widget would crash rendering an unknown phase.
    for name in PHASES:
        assert name in phase_mod.PHASE_GLYPH
        assert name in phase_mod.PHASE_COLOR_TOKEN


def test_empty_string_timestamp_does_not_crash() -> None:
    # cockpit_events created_at could be empty in pathological cases.
    p = derive_phase(
        [{"id": 1, "kind": "graph_delta", "payload": {}, "created_at": ""}],
        now=_NOW,
    )
    # No timestamp → treated as inside-window; single event still anti-flickers.
    assert p.name == "idle"


def test_narrate_does_not_outrank_other_phases() -> None:
    # agent_narration alone shouldn't override a verify signal.
    p = derive_phase(
        [
            _ev(1, "agent_narration", t=40.0, payload={"text": "thinking"}),
            _ev(2, "agent_narration", t=45.0, payload={"text": "checking"}),
            _ev(3, "prereg_locked", t=50.0),
            _ev(4, "seed_run_recorded", t=55.0),
        ],
        now=_NOW,
    )
    # narrate has 2, verify has 2 — tie broken by recency → verify
    assert p.name == "verify"


def test_returns_frozen_phase_instance() -> None:
    p = derive_phase([], now=_NOW)
    assert isinstance(p, Phase)
    # Frozen dataclass — mutation should fail.
    with pytest.raises(Exception):
        p.name = "explore"  # type: ignore[misc]


def test_derive_phase_from_db_returns_idle_on_empty(workspace) -> None:
    # No events written to cockpit_events → derive_phase_from_db must
    # cleanly return idle, not crash.
    from cockpit import phase as phase_mod

    p = phase_mod.derive_phase_from_db()
    assert p.name == "idle"


def test_derive_phase_from_db_picks_up_recent_events(workspace) -> None:
    from cockpit import data as cockpit_data
    from cockpit import phase as phase_mod

    cockpit_data.record_event("graph_delta", {"node_id": "hyp_01", "kind": "hypothesis"})
    cockpit_data.record_event("graph_delta", {"node_id": "hyp_02", "kind": "hypothesis"})
    p = phase_mod.derive_phase_from_db()
    assert p.name == "explore"


def test_explicit_phase_set_via_db_round_trip(workspace) -> None:
    from cockpit import data as cockpit_data
    from cockpit import phase as phase_mod

    cockpit_data.record_event(
        "phase_set",
        {"phase": "prove", "focus_nodes": ["prop_42"], "intent": "Drafting"},
    )
    p = phase_mod.derive_phase_from_db()
    assert p.name == "prove"
    assert "prop_42" in p.focus_nodes
