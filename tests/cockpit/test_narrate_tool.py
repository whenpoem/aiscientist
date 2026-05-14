"""Tests for the v5.0 cockpit__narrate atomic tool."""

from __future__ import annotations

import pytest


def _fetch_events(workspace) -> list[dict]:
    from cockpit import data as cockpit_data
    return cockpit_data.fetch_new_events(last_event_id=0, limit=2000)


def test_narrate_happy_path_writes_event(workspace):
    from cockpit import mcp_server

    result = mcp_server.narrate(
        text="Choosing hyp_03 over hyp_05 because the literature supports it.",
        scope="node:hyp_03",
    )
    assert result["ok"] is True

    events = _fetch_events(workspace)
    matching = [e for e in events if e["kind"] == "agent_narration"]
    assert len(matching) == 1
    payload = matching[0]["payload"]
    assert payload["text"].startswith("Choosing hyp_03")
    assert payload["scope"] == "node:hyp_03"


def test_narrate_defaults_scope_to_session(workspace):
    from cockpit import mcp_server

    mcp_server.narrate(text="now drafting")
    events = _fetch_events(workspace)
    payload = next(e for e in events if e["kind"] == "agent_narration")["payload"]
    assert payload["scope"] == "session"


def test_narrate_empty_text_raises(workspace):
    from cockpit import mcp_server

    with pytest.raises(ValueError, match="non-empty"):
        mcp_server.narrate(text="   ")


def test_narrate_text_over_500_chars_truncated(workspace):
    from cockpit import mcp_server

    long_text = "x" * 750
    mcp_server.narrate(text=long_text)
    events = _fetch_events(workspace)
    payload = next(e for e in events if e["kind"] == "agent_narration")["payload"]
    assert len(payload["text"]) <= 500
    assert payload["text"].endswith("…")


def test_narrate_invalid_scope_raises(workspace):
    from cockpit import mcp_server

    with pytest.raises(ValueError, match="scope must match"):
        mcp_server.narrate(text="hello", scope="random-scope-value")


def test_narrate_branch_scope_accepted(workspace):
    from cockpit import mcp_server

    result = mcp_server.narrate(text="trying counterfactual", scope="branch:abc123")
    assert result["ok"] is True


def test_narrate_node_scope_must_match_node_regex(workspace):
    from cockpit import mcp_server

    # Empty node id after the "node:" prefix is rejected by the scope regex.
    with pytest.raises(ValueError, match="scope must match"):
        mcp_server.narrate(text="x", scope="node:")


def test_narrate_does_not_emit_phase_set(workspace):
    """Narrate is the soft-monologue channel; it must not silently
    change the derived phase by piggybacking on phase_set.
    """
    from cockpit import data as cockpit_data
    from cockpit import mcp_server

    before = [e for e in cockpit_data.fetch_new_events(0, 2000) if e["kind"] == "phase_set"]
    mcp_server.narrate(text="just thinking out loud")
    after = [e for e in cockpit_data.fetch_new_events(0, 2000) if e["kind"] == "phase_set"]
    assert len(after) == len(before)
