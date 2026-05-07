"""compose_correction_prompt + apply_correction (P3)."""

from __future__ import annotations

import pytest


def _setup(prove_impl, memory_impl):
    memory_impl.record_failure(
        "Cauchy-Schwarz without finite second moment",
        "applied CS without checking E[X^2]<inf",
        "missing assumption",
        "verify finite moments first",
        domain="proof",
    )
    prop = prove_impl.propose_proposition("Var bound via CS")
    skel = prove_impl.propose_proof_skeleton(prop["node_id"], "outline")
    draft = prove_impl.register_proof_draft(skel["node_id"], "original draft body")
    seg = prove_impl.segment_proof(
        draft["node_id"],
        ["Apply Cauchy-Schwarz: E[XY]^2 <= E[X^2]E[Y^2].", "Conclude Var bound."],
    )
    prove_impl.register_diagnosis(
        seg["manifest_id"],
        seg["snippet_ids"][0],
        True,
        "missing finite second moment check",
        matched_failure_ids=[1],
    )
    prove_impl.register_diagnosis(
        seg["manifest_id"],
        seg["snippet_ids"][1],
        False,
        "ok",
    )
    return draft["node_id"], seg["manifest_id"]


def test_compose_correction_prompt_lists_only_flawed(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    draft_id, manifest_id = _setup(prove, memory)

    out = prove.compose_correction_prompt(draft_id, manifest_id)
    assert out["draft_id"] == draft_id
    assert out["manifest_id"] == manifest_id
    assert out["flawed_count"] == 1
    # The prompt assembles the original draft body + the per-flaw
    # descriptions. Both must be present so the agent has full context.
    assert "original draft body" in out["prompt"]
    assert "missing finite second moment check" in out["prompt"]


def test_compose_correction_prompt_rejects_mismatched_manifest(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    draft_a, manifest_a = _setup(prove, memory)

    prop = prove.propose_proposition("other prop")
    skel = prove.propose_proof_skeleton(prop["node_id"], "outline")
    draft_b = prove.register_proof_draft(skel["node_id"], "draft b")

    with pytest.raises(ValueError, match="belongs to draft"):
        prove.compose_correction_prompt(draft_b["node_id"], manifest_a)


def test_apply_correction_creates_new_revision_and_marks_applied(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]
    draft_id, manifest_id = _setup(prove, memory)

    out = prove.apply_correction(
        draft_id, manifest_id, "corrected LaTeX body", note="fixed CS step"
    )
    assert out["new_draft_id"].startswith("psk_")
    assert out["old_draft_id"] == draft_id
    assert out["manifest_status"] == "applied"

    con = db._connect()
    try:
        new_node = con.execute(
            "SELECT kind, parent_id, text FROM mem_nodes WHERE node_id = ?",
            (out["new_draft_id"],),
        ).fetchone()
    finally:
        con.close()
    assert new_node["kind"] == "proof_skeleton"
    assert new_node["parent_id"] == draft_id
    assert new_node["text"] == "corrected LaTeX body"

    manifests = prove.list_diagnostic_manifests(draft_id=draft_id)
    assert manifests[0]["status"] == "applied"


def test_apply_correction_rejects_already_applied(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    draft_id, manifest_id = _setup(prove, memory)
    prove.apply_correction(draft_id, manifest_id, "first correction")
    with pytest.raises(ValueError, match="already applied"):
        prove.apply_correction(draft_id, manifest_id, "second attempt")


def test_apply_correction_requires_non_empty(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    draft_id, manifest_id = _setup(prove, memory)
    with pytest.raises(ValueError, match="non-empty"):
        prove.apply_correction(draft_id, manifest_id, "   ")
