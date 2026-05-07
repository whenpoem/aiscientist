"""mem_failures.domain semantics (P1 / ADR 0008).

The failure ledger is shared between the empirical and proof trunks; the
``domain`` column scopes filtering. Default for record_failure is
``empirical`` (v3.0 backward compat). Default for match_signatures is
``None`` (cross-domain), which is the cross-trunk failure-leverage
described in architecture.md §13.
"""

from __future__ import annotations

import pytest


def test_record_failure_defaults_to_empirical(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    result = impl.record_failure(
        "training oom", "cuda crash at epoch 1", "batch too big", "halve batch"
    )

    assert result["domain"] == "empirical"
    con = db._connect()
    try:
        row = con.execute(
            "SELECT domain FROM mem_failures WHERE failure_id = ?",
            (result["failure_id"],),
        ).fetchone()
    finally:
        con.close()
    assert row["domain"] == "empirical"


def test_record_failure_accepts_proof_domain(workspace):
    impl = workspace["memory_mcp.impl"]

    result = impl.record_failure(
        "Cauchy-Schwarz used",
        "no finite second moment check",
        "missing assumption",
        "verify E[X^2] < inf before applying",
        domain="proof",
    )

    assert result["domain"] == "proof"


def test_record_failure_rejects_unknown_domain(workspace):
    impl = workspace["memory_mcp.impl"]

    with pytest.raises(ValueError):
        impl.record_failure("trigger", "symptom", domain="cosmic")


def test_match_signatures_default_is_cross_domain(workspace):
    impl = workspace["memory_mcp.impl"]

    impl.record_failure(
        "off-by-one in slice",
        "test metric looked weirdly perfect",
        "wrong index",
        "use [:-1] not [:]",
        domain="empirical",
    )
    impl.record_failure(
        "off-by-one in summation index",
        "proof step skipped boundary",
        "wrong index in sum bounds",
        "rewrite sum to start at i=1",
        domain="proof",
    )

    matches = impl.match_signatures("off-by-one index")
    domains = {row["domain"] for row in matches}
    assert "empirical" in domains
    assert "proof" in domains


def test_match_signatures_filters_to_empirical(workspace):
    impl = workspace["memory_mcp.impl"]

    impl.record_failure(
        "training oom", "cuda crash", "batch too big", "halve batch", domain="empirical"
    )
    impl.record_failure(
        "Cauchy-Schwarz",
        "no finite second moment",
        "missing assumption",
        "verify",
        domain="proof",
    )

    matches = impl.match_signatures("training cuda crash", domain="empirical")
    assert len(matches) >= 1
    assert all(row["domain"] == "empirical" for row in matches)


def test_match_signatures_filters_to_proof(workspace):
    impl = workspace["memory_mcp.impl"]

    impl.record_failure(
        "training oom", "cuda crash", "batch", "halve", domain="empirical"
    )
    impl.record_failure(
        "Cauchy-Schwarz used",
        "no finite second moment check",
        "missing assumption",
        "verify",
        domain="proof",
    )

    matches = impl.match_signatures("Cauchy-Schwarz", domain="proof")
    assert len(matches) >= 1
    assert all(row["domain"] == "proof" for row in matches)


def test_match_signatures_rejects_unknown_domain(workspace):
    impl = workspace["memory_mcp.impl"]

    with pytest.raises(ValueError):
        impl.match_signatures("anything", domain="cosmic")
