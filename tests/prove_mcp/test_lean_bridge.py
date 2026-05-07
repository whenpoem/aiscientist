"""record_lean_attempt + list_lean_attempts (P4).

The agent layer would normally orchestrate the actual lean-lsp-mcp call;
here we treat that as out-of-scope for unit tests and verify only the
persistence + audit-trail invariants. The cross-trunk side effects
(attach_evidence on success, record_failure on failure) are deliberately
*not* triggered automatically by record_lean_attempt -- the prover
agent's prompt makes those calls explicitly so each side effect is
visible in the cockpit event stream. We verify that intentional
decoupling here.
"""

from __future__ import annotations

import pytest


def _proposition(impl) -> str:
    out = impl.propose_proposition(
        "Sample mean is unbiased estimator of expectation under iid sampling"
    )
    return out["node_id"]


def test_record_lean_attempt_verified_persists_audit_row(workspace):
    impl = workspace["prove_mcp.impl"]
    pid = _proposition(impl)
    triage = impl.triage_for_formalization(pid)
    out = impl.record_lean_attempt(
        proposition_id=pid,
        status="verified",
        lean_source="theorem ex (X : Fin n -> R) ... := add_comm ...",
        duration_sec=12.5,
        triage=triage,
    )
    assert out["status"] == "verified"
    assert out["attempt_id"] >= 1
    rows = impl.list_lean_attempts(proposition_id=pid)
    assert len(rows) == 1
    assert rows[0]["status"] == "verified"
    assert rows[0]["duration_sec"] == 12.5
    assert rows[0]["triage_eligible"] is True


def test_record_lean_attempt_failed(workspace):
    impl = workspace["prove_mcp.impl"]
    pid = _proposition(impl)
    triage = impl.triage_for_formalization(pid)
    impl.record_lean_attempt(
        proposition_id=pid,
        status="failed",
        lean_source="theorem ex ... := sorry",
        stderr="error: type mismatch",
        duration_sec=180.0,
        triage=triage,
    )
    rows = impl.list_lean_attempts(proposition_id=pid, status="failed")
    assert len(rows) == 1
    assert rows[0]["stderr"] == "error: type mismatch"


def test_record_lean_attempt_without_triage_payload(workspace):
    impl = workspace["prove_mcp.impl"]
    pid = _proposition(impl)
    impl.record_lean_attempt(proposition_id=pid, status="queued")
    rows = impl.list_lean_attempts(proposition_id=pid)
    assert rows[0]["status"] == "queued"
    assert rows[0]["triage_eligible"] is False
    assert rows[0]["triage_difficulty"] == "unknown"


def test_record_lean_attempt_does_not_auto_attach_evidence(workspace):
    """Verifies the architectural invariant: cross-trunk side effects are
    the agent's job, not record_lean_attempt's. A successful attempt must
    NOT silently call attach_evidence."""
    prove = workspace["prove_mcp.impl"]
    memory_db = workspace["memory_mcp.db"]
    pid = _proposition(prove)
    triage = prove.triage_for_formalization(pid)
    prove.record_lean_attempt(
        proposition_id=pid,
        status="verified",
        lean_source="theorem ok := ...",
        triage=triage,
    )
    con = memory_db._connect()
    try:
        evidence = con.execute(
            """
            SELECT count(*) AS n FROM mem_nodes
            WHERE kind = 'evidence' AND parent_id = ?
            """,
            (pid,),
        ).fetchone()
    finally:
        con.close()
    assert evidence["n"] == 0, (
        "record_lean_attempt(verified=True) must NOT auto-create evidence; "
        "the prover agent attaches evidence in a separate, auditable step"
    )


def test_record_lean_attempt_rejects_invalid_status(workspace):
    impl = workspace["prove_mcp.impl"]
    pid = _proposition(impl)
    with pytest.raises(ValueError, match="status"):
        impl.record_lean_attempt(proposition_id=pid, status="success")


def test_record_lean_attempt_rejects_negative_duration(workspace):
    impl = workspace["prove_mcp.impl"]
    pid = _proposition(impl)
    with pytest.raises(ValueError, match="non-negative"):
        impl.record_lean_attempt(proposition_id=pid, status="verified", duration_sec=-1.0)


def test_record_lean_attempt_rejects_invalid_difficulty(workspace):
    impl = workspace["prove_mcp.impl"]
    pid = _proposition(impl)
    with pytest.raises(ValueError, match="difficulty"):
        impl.record_lean_attempt(
            proposition_id=pid,
            status="queued",
            triage={"eligible": True, "estimated_difficulty": "trivial"},
        )


def test_record_lean_attempt_rejects_non_proposition(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    hyp = memory.propose_hypothesis("dropout helps")
    with pytest.raises(ValueError, match="proposition"):
        prove.record_lean_attempt(proposition_id=hyp["node_id"], status="queued")


def test_list_lean_attempts_filters_by_status(workspace):
    impl = workspace["prove_mcp.impl"]
    pid = _proposition(impl)
    triage = impl.triage_for_formalization(pid)
    impl.record_lean_attempt(pid, "queued", triage=triage)
    impl.record_lean_attempts_for_test = None  # ensure only the public API used
    impl.record_lean_attempt(pid, "running", triage=triage)
    impl.record_lean_attempt(pid, "verified", triage=triage)

    verified_only = impl.list_lean_attempts(proposition_id=pid, status="verified")
    assert len(verified_only) == 1
    assert verified_only[0]["status"] == "verified"

    all_attempts = impl.list_lean_attempts(proposition_id=pid)
    assert len(all_attempts) == 3


def test_list_lean_attempts_invalid_status_raises(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError):
        impl.list_lean_attempts(status="cosmic")
