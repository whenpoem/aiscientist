"""triage_for_formalization heuristics (P4)."""

from __future__ import annotations

import pytest


def test_triage_eligible_short_whitelisted_proposition(workspace):
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition(
        "Sample mean of iid samples is unbiased estimator of expectation"
    )
    out = impl.triage_for_formalization(prop["node_id"])
    assert out["eligible"] is True
    assert out["estimated_difficulty"] == "low"
    assert "sample mean" in out["whitelist_hits"] or "expectation" in out["whitelist_hits"]
    assert out["blacklist_hits"] == []


def test_triage_rejects_too_short(workspace):
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition("E[X]=mu")
    out = impl.triage_for_formalization(prop["node_id"])
    assert out["eligible"] is False
    assert any("too short" in r for r in out["reasons"])


def test_triage_rejects_too_long(workspace):
    impl = workspace["prove_mcp.impl"]
    long_text = (
        "Consider a sample mean estimator with iid samples. "
        + "We discuss in great pedagogical detail every motivation, every related "
        * 12
    )
    prop = impl.propose_proposition(long_text)
    out = impl.triage_for_formalization(prop["node_id"])
    assert out["eligible"] is False
    assert any("too long" in r for r in out["reasons"])


def test_triage_rejects_no_whitelist_keyword(workspace):
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition(
        "Some completely unrelated abstract claim with no statistical "
        "vocabulary present here at all today"
    )
    out = impl.triage_for_formalization(prop["node_id"])
    assert out["eligible"] is False
    assert any("mathlib-friendly" in r for r in out["reasons"])


def test_triage_rejects_blacklist_hit(workspace):
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition(
        "By Brownian motion + ito calculus, the variance of the sample mean "
        "satisfies a stochastic differential inequality."
    )
    out = impl.triage_for_formalization(prop["node_id"])
    assert out["eligible"] is False
    assert "brownian motion" in out["blacklist_hits"]
    assert "ito" in out["blacklist_hits"]


def test_triage_difficulty_med_when_long_but_eligible(workspace):
    impl = workspace["prove_mcp.impl"]
    body = (
        "Under iid sampling, the sample mean estimator satisfies linearity of "
        "expectation, and by independence the variance scales as 1/n. "
        "The Cauchy-Schwarz inequality implies the moment bound used below."
    )
    prop = impl.propose_proposition(body)
    out = impl.triage_for_formalization(prop["node_id"])
    assert out["eligible"] is True
    assert out["estimated_difficulty"] in {"low", "med"}


def test_triage_unknown_proposition_raises(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="Unknown proposition"):
        impl.triage_for_formalization("prop_not_real")


def test_triage_rejects_non_proposition_node(workspace):
    impl = workspace["prove_mcp.impl"]
    memory_impl = workspace["memory_mcp.impl"]
    hyp = memory_impl.propose_hypothesis("dropout helps")
    with pytest.raises(ValueError, match="proposition"):
        impl.triage_for_formalization(hyp["node_id"])
