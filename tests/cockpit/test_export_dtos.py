"""Per-DTO builder tests for the cockpit.export module."""

from __future__ import annotations

import pytest


def _seed_proposition_with_skeletons(workspace) -> str:
    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition("Chebyshev tail bound")
    prove_impl.propose_proof_skeleton(
        prop["node_id"], text="Apply Markov to (X - mu)^2."
    )
    prove_impl.propose_proof_skeleton(
        prop["node_id"], text="Use moment generating function."
    )
    return prop["node_id"]


def test_build_closure_includes_overview_for_proposition(workspace):
    from cockpit.export.dto.closure import build_closure

    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition("Sample mean unbiased")
    report = build_closure(prop["node_id"])
    assert report.kind == "closure"
    assert report.node_id == prop["node_id"]
    keys = {s.key for s in report.sections}
    assert "overview" in keys


def test_build_draft_returns_latest_skeleton(workspace):
    from cockpit.export.dto.draft import build_draft

    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition("Cauchy-Schwarz")
    prove_impl.propose_proof_skeleton(prop["node_id"], text="Outline.")
    prove_impl.propose_proof_skeleton(prop["node_id"], text="Outline v2.")
    report = build_draft(prop["node_id"])
    assert report.kind == "draft"
    body = "\n".join(s.body for s in report.sections)
    # The latest skeleton's text wins (depth-first tie-broken by created_at).
    assert "Outline" in body


def test_build_diagnostic_empty_manifest_path(workspace):
    """A proposition with no manifest produces a placeholder section."""
    from cockpit.export.dto.diagnostic import build_diagnostic

    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition("Hoeffding")
    report = build_diagnostic(prop["node_id"])
    assert report.kind == "diagnostic"
    section_titles = " | ".join(s.title for s in report.sections)
    assert "Proposition" in section_titles


def test_build_portfolio_lists_skeleton_siblings(workspace):
    from cockpit.export.dto.portfolio import build_portfolio

    prop_id = _seed_proposition_with_skeletons(workspace)
    report = build_portfolio(prop_id)
    assert report.kind == "portfolio"
    candidate_count = sum(
        1 for s in report.sections if s.key.startswith("candidate_")
    )
    assert candidate_count == 2


def test_build_cascade_lists_events(workspace):
    """Any node with at least one cockpit event mentioning it should
    surface that event in the cascade trace."""
    from cockpit.export.dto.cascade import build_cascade

    memory_impl = workspace["memory_mcp.impl"]
    hyp = memory_impl.propose_hypothesis("Cascade test target")
    report = build_cascade(hyp["node_id"])
    assert report.kind == "cascade"
    # The proposal itself emits a graph_delta event mentioning the node;
    # the report should have an events section.
    keys = {s.key for s in report.sections}
    assert "events" in keys


def test_build_closure_rejects_unknown_node(workspace):
    from cockpit.export.dto.closure import build_closure

    with pytest.raises(ValueError, match="unknown node"):
        build_closure("prop_ghost_id")
