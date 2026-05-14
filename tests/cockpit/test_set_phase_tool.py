"""Tests for the v5.0 cockpit__set_phase atomic tool."""

from __future__ import annotations

import json

import pytest


def _connect_and_fetch(workspace) -> list[dict]:
    """Return all cockpit_events rows for assertions."""
    from cockpit import data as cockpit_data
    return cockpit_data.fetch_new_events(last_event_id=0, limit=2000)


def test_set_phase_happy_path_writes_event(workspace):
    from cockpit import mcp_server

    result = mcp_server.set_phase(
        phase="prove",
        focus_nodes=["prop_42", "prop_43"],
        intent="Drafting NL proof for Markov bound",
    )
    assert result["ok"] is True
    assert isinstance(result["event_id"], int)

    events = _connect_and_fetch(workspace)
    matching = [e for e in events if e["kind"] == "phase_set"]
    assert len(matching) == 1
    payload = matching[0]["payload"]
    assert payload["phase"] == "prove"
    assert payload["focus_nodes"] == ["prop_42", "prop_43"]
    assert payload["intent"] == "Drafting NL proof for Markov bound"


def test_set_phase_invalid_phase_raises(workspace):
    from cockpit import mcp_server

    with pytest.raises(ValueError, match="phase must be one of"):
        mcp_server.set_phase(phase="banana")


def test_set_phase_invalid_focus_node_id_raises(workspace):
    from cockpit import mcp_server

    with pytest.raises(ValueError, match="focus_nodes entry"):
        mcp_server.set_phase(
            phase="explore",
            focus_nodes=["BAD-ID-WITH-DASH"],
        )


def test_set_phase_truncates_intent_to_200_chars(workspace):
    from cockpit import mcp_server

    long_intent = "x" * 500
    result = mcp_server.set_phase(phase="idle", intent=long_intent)
    assert result["ok"] is True

    events = _connect_and_fetch(workspace)
    payload = next(e for e in events if e["kind"] == "phase_set")["payload"]
    assert len(payload["intent"]) <= 200


def test_set_phase_caps_focus_nodes_to_8(workspace):
    from cockpit import mcp_server

    nodes = [f"hyp_n{i:02d}" for i in range(15)]
    result = mcp_server.set_phase(phase="select", focus_nodes=nodes)
    assert result["ok"] is True

    events = _connect_and_fetch(workspace)
    payload = next(e for e in events if e["kind"] == "phase_set")["payload"]
    assert len(payload["focus_nodes"]) == 8


def test_set_phase_skips_empty_and_blank_focus_entries(workspace):
    from cockpit import mcp_server

    result = mcp_server.set_phase(
        phase="explore",
        focus_nodes=["hyp_one", "", "  ", "hyp_two"],
    )
    assert result["ok"] is True

    events = _connect_and_fetch(workspace)
    payload = next(e for e in events if e["kind"] == "phase_set")["payload"]
    assert payload["focus_nodes"] == ["hyp_one", "hyp_two"]


def test_set_phase_idempotent_in_emission(workspace):
    """Two consecutive set_phase calls emit two separate events — the
    cockpit's derivation reads only the latest, but the audit trail
    keeps both.
    """
    from cockpit import mcp_server

    mcp_server.set_phase(phase="explore")
    mcp_server.set_phase(phase="select")
    events = _connect_and_fetch(workspace)
    matching = [e for e in events if e["kind"] == "phase_set"]
    assert len(matching) == 2
    # Newest is "select" (ASC order means index -1 is newest).
    assert matching[-1]["payload"]["phase"] == "select"


def test_set_phase_payload_round_trips_through_json(workspace):
    """record_event stores payload as JSON. Make sure the dict survives
    the round-trip without losing structure.
    """
    from cockpit import mcp_server

    mcp_server.set_phase(
        phase="verify",
        focus_nodes=["hyp_x"],
        intent="checking",
    )
    events = _connect_and_fetch(workspace)
    payload = next(e for e in events if e["kind"] == "phase_set")["payload"]
    # payload should already be a dict after fetch_new_events' parsing.
    assert isinstance(payload, dict)
    # And re-encoding should be lossless.
    assert json.loads(json.dumps(payload)) == payload
