"""segment_proof + list_proof_snippets (P3)."""

from __future__ import annotations

import pytest


def _setup_draft(impl) -> str:
    prop = impl.propose_proposition("Sample mean is unbiased for iid samples")
    skel = impl.propose_proof_skeleton(prop["node_id"], "Use linearity of E[].")
    draft = impl.register_proof_draft(skel["node_id"], "Full LaTeX body")
    return draft["node_id"]


def test_segment_creates_snippets_and_open_manifest(workspace):
    impl = workspace["prove_mcp.impl"]
    db = workspace["memory_mcp.db"]

    draft_id = _setup_draft(impl)
    out = impl.segment_proof(
        draft_id,
        [
            "Step 1: define the sample mean as $\\bar{X} = (1/n) \\sum X_i$.",
            "Step 2: by linearity, $E[\\bar{X}] = (1/n) \\sum E[X_i]$.",
            "Step 3: each E[X_i] = mu, so $E[\\bar{X}] = mu$.",
        ],
    )
    assert len(out["snippet_ids"]) == 3
    assert out["manifest_id"] >= 1

    con = db._connect()
    try:
        snippets = con.execute(
            "SELECT node_id, kind, parent_id FROM mem_nodes "
            "WHERE kind = 'proof_snippet' ORDER BY created_at"
        ).fetchall()
    finally:
        con.close()
    assert len(snippets) == 3
    assert all(row["parent_id"] == draft_id for row in snippets)

    manifests = impl.list_diagnostic_manifests(draft_id=draft_id)
    assert len(manifests) == 1
    assert manifests[0]["status"] == "open"
    assert manifests[0]["entry_count"] == 0


def test_segment_strips_blanks_and_rejects_empty(workspace):
    impl = workspace["prove_mcp.impl"]
    draft_id = _setup_draft(impl)

    out = impl.segment_proof(
        draft_id,
        ["valid step", "  ", "", "  another step  "],
    )
    assert len(out["snippet_ids"]) == 2

    with pytest.raises(ValueError, match="non-empty"):
        impl.segment_proof(draft_id, ["", "  "])


def test_segment_rejects_non_skeleton_parent(workspace):
    impl = workspace["prove_mcp.impl"]
    prop = impl.propose_proposition("foo")
    with pytest.raises(ValueError, match="proof_skeleton draft"):
        impl.segment_proof(prop["node_id"], ["snippet"])


def test_list_proof_snippets_orders_by_creation(workspace):
    impl = workspace["prove_mcp.impl"]
    draft_id = _setup_draft(impl)
    impl.segment_proof(draft_id, ["alpha", "beta", "gamma"])

    snippets = impl.list_proof_snippets(draft_id)
    texts = [row["text"] for row in snippets]
    assert texts == ["alpha", "beta", "gamma"]
