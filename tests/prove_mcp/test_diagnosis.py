"""diagnose_snippet / register_diagnosis / finalize_manifest (P3)."""

from __future__ import annotations

import pytest


def _seed_proof_failures(memory_impl):
    memory_impl.record_failure(
        "Cauchy-Schwarz applied without finite second moment",
        "concluded E[XY]^2 <= E[X^2] E[Y^2] without verifying E[X^2] < inf",
        "missing finite-second-moment hypothesis",
        "verify E[X^2] < inf and E[Y^2] < inf before applying Cauchy-Schwarz",
        domain="proof",
    )
    memory_impl.record_failure(
        "linearity of E[] applied to dependent random variables",
        "claimed E[X1 + X2] = E[X1] + E[X2] without noting independence not required",
        "linearity does not require independence; mistake was elsewhere",
        "linearity holds unconditionally; recheck ancillary step",
        domain="proof",
    )


def _setup_segmented_draft(prove_impl, memory_impl) -> tuple[str, list[str], int]:
    _seed_proof_failures(memory_impl)
    prop = prove_impl.propose_proposition("Var(X+Y) bound via Cauchy-Schwarz")
    skel = prove_impl.propose_proof_skeleton(prop["node_id"], "outline using CS")
    draft = prove_impl.register_proof_draft(skel["node_id"], "draft body")
    seg = prove_impl.segment_proof(
        draft["node_id"],
        [
            "Apply Cauchy-Schwarz: E[XY]^2 <= E[X^2] E[Y^2].",
            "Conclude Var(X+Y) <= 4 max(Var X, Var Y).",
        ],
    )
    return draft["node_id"], seg["snippet_ids"], seg["manifest_id"]


def test_diagnose_snippet_returns_proof_domain_candidates(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    _, snippet_ids, _ = _setup_segmented_draft(prove, memory)

    result = prove.diagnose_snippet(snippet_ids[0])
    assert result["snippet_id"] == snippet_ids[0]
    assert "Cauchy-Schwarz" in result["snippet_text"]
    assert isinstance(result["candidates"], list)
    assert len(result["candidates"]) >= 1
    # Candidates must come from the proof domain (cross-domain matching is
    # the architecture.md §13 cooperation; here we want only proof-domain
    # entries because the agent passes domain='proof').
    assert all(c["domain"] == "proof" for c in result["candidates"])
    # Top candidate should be the matching Cauchy-Schwarz error.
    assert "Cauchy-Schwarz" in result["candidates"][0]["trigger"]
    assert "is_flawed" in result["prompt"]


def test_diagnose_snippet_unknown_id_raises(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="Unknown snippet"):
        impl.diagnose_snippet("psnp_does_not_exist")


def test_diagnose_snippet_rejects_non_snippet_node(workspace):
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition("foo")
    with pytest.raises(ValueError, match="proof_snippet"):
        impl.diagnose_snippet(prop["node_id"])


def test_register_diagnosis_appends_entry(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    _, snippet_ids, manifest_id = _setup_segmented_draft(prove, memory)

    out = prove.register_diagnosis(
        manifest_id=manifest_id,
        snippet_id=snippet_ids[0],
        is_flawed=True,
        description="Cauchy-Schwarz applied without finite-second-moment check",
        matched_failure_ids=[1],
    )
    assert out["manifest_id"] == manifest_id
    assert out["entry_count"] == 1

    manifests = prove.list_diagnostic_manifests(status="open")
    assert len(manifests) == 1
    assert manifests[0]["entry_count"] == 1
    assert manifests[0]["entries"][0]["is_flawed"] is True


def test_register_diagnosis_rejects_wrong_snippet(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    _, snippet_ids, manifest_id = _setup_segmented_draft(prove, memory)
    # Set up a second draft with its own snippets.
    prop = prove.propose_proposition("other")
    skel = prove.propose_proof_skeleton(prop["node_id"], "outline")
    other_draft = prove.register_proof_draft(skel["node_id"], "other draft body")
    other_seg = prove.segment_proof(other_draft["node_id"], ["other snippet"])

    with pytest.raises(ValueError, match="does not belong to draft"):
        prove.register_diagnosis(
            manifest_id=manifest_id,
            snippet_id=other_seg["snippet_ids"][0],
            is_flawed=False,
            description="cross-draft attempt",
        )


def test_register_diagnosis_rejects_after_finalise(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    _, snippet_ids, manifest_id = _setup_segmented_draft(prove, memory)
    prove.register_diagnosis(
        manifest_id=manifest_id,
        snippet_id=snippet_ids[0],
        is_flawed=False,
        description="ok",
    )
    prove.finalize_manifest(manifest_id)
    with pytest.raises(ValueError, match="status"):
        prove.register_diagnosis(
            manifest_id=manifest_id,
            snippet_id=snippet_ids[1],
            is_flawed=False,
            description="too late",
        )


def test_finalize_manifest_empty_path(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    _, snippet_ids, manifest_id = _setup_segmented_draft(prove, memory)
    prove.register_diagnosis(manifest_id, snippet_ids[0], False, "ok")
    prove.register_diagnosis(manifest_id, snippet_ids[1], False, "ok")

    out = prove.finalize_manifest(manifest_id)
    assert out["status"] == "empty"
    assert out["flawed_count"] == 0


def test_finalize_manifest_open_path_when_flawed(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    _, snippet_ids, manifest_id = _setup_segmented_draft(prove, memory)
    prove.register_diagnosis(manifest_id, snippet_ids[0], True, "needs fix")
    prove.register_diagnosis(manifest_id, snippet_ids[1], False, "ok")

    out = prove.finalize_manifest(manifest_id)
    assert out["status"] == "open"
    assert out["flawed_count"] == 1


def test_list_diagnostic_manifests_filters(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    draft_a, snip_a, mid_a = _setup_segmented_draft(prove, memory)

    prop = prove.propose_proposition("other prop")
    skel = prove.propose_proof_skeleton(prop["node_id"], "outline")
    draft_b = prove.register_proof_draft(skel["node_id"], "second draft body")
    seg_b = prove.segment_proof(draft_b["node_id"], ["another"])
    mid_b = seg_b["manifest_id"]

    by_a = prove.list_diagnostic_manifests(draft_id=draft_a)
    assert {row["manifest_id"] for row in by_a} == {mid_a}

    open_only = prove.list_diagnostic_manifests(status="open")
    assert {row["manifest_id"] for row in open_only} == {mid_a, mid_b}


def test_list_diagnostic_manifests_invalid_status_raises(workspace):
    prove = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError):
        prove.list_diagnostic_manifests(status="cosmic")
