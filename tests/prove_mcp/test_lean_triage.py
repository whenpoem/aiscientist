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
    # Bug B/C fix: blacklist now uses multi-word phrases to avoid substring
    # false-positives. 'ito calculus' instead of bare 'ito'.
    assert "ito calculus" in out["blacklist_hits"]
    assert "stochastic differential" in out["blacklist_hits"]


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


def test_triage_accepts_extended_whitelist(workspace):
    """Bug A fix: extended whitelist covers Borel-Cantelli, Hoeffding,
    Rao-Blackwell, sub-Gaussian, KL, etc. — propositions that obviously
    belong in mathlib's coverage but were rejected by the v1 keyword set."""
    impl = workspace["prove_mcp.impl"]
    cases = [
        "Borel-Cantelli first lemma: summable probabilities exclude i.o. events",
        "Hoeffding inequality for bounded independent sums",
        "Rao-Blackwell theorem: conditioning on a sufficient statistic",
        "sub-gaussian tail bound from MGF control",
        "Pinsker inequality bounding TV by sqrt of KL divergence",
        "Glivenko-Cantelli: empirical CDF converges uniformly almost surely",
    ]
    for text in cases:
        prop = impl.propose_proposition(text)
        out = impl.triage_for_formalization(prop["node_id"])
        assert out["eligible"], f"expected eligible for {text!r}; got {out}"
        assert out["estimated_difficulty"] in {"low", "med"}


def test_triage_word_boundary_no_false_positive(workspace):
    """Bug C fix: 'controls' must not trigger an 'ols' whitelist hit."""
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition(
        "We compare across experimental controls and check the moment estimate."
    )
    out = impl.triage_for_formalization(prop["node_id"])
    assert "ols" not in out["whitelist_hits"], (
        f"'ols' substring matched 'controls'; whitelist_hits={out['whitelist_hits']}"
    )


def test_triage_rejected_difficulty_is_na(workspace):
    """Bug D fix: rejected propositions get difficulty='n/a', not 'high'."""
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition(
        "Use Brownian motion stochastic differential equation."
    )
    out = impl.triage_for_formalization(prop["node_id"])
    assert out["eligible"] is False
    assert out["estimated_difficulty"] == "n/a"


def test_triage_lebesgue_no_longer_blacklisted(workspace):
    """Bug B fix: 'lebesgue integral' was over-aggressively blacklisted;
    mathlib has full Lebesgue integration coverage. A proposition mentioning
    a Lebesgue integral should be allowed if it has whitelist hits."""
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition(
        "By dominated convergence, the Lebesgue integral of f_n converges "
        "to the integral of f, giving the moment bound and concentration."
    )
    out = impl.triage_for_formalization(prop["node_id"])
    assert out["eligible"] is True, f"unexpectedly rejected: {out}"


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
