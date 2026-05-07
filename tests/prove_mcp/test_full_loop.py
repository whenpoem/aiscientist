"""End-to-end NL workflow integration test (P3).

Walk one complete proof through the proof trunk:
ingest_proof_corpus -> retrieve_skeletons -> propose_proposition ->
propose_proof_skeleton -> register_proof_draft -> segment_proof ->
diagnose_snippet (per snippet) -> register_diagnosis ->
finalize_manifest -> apply_correction. Verify the manifest closes
applied, the corrected draft is a child revision, and the cross-domain
failure ledger has been queried (via diagnose_snippet returning
proof-domain candidates).
"""

from __future__ import annotations


def test_complete_proof_loop(workspace):
    prove = workspace["prove_mcp.impl"]
    memory = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    # 1. Seed a proof-domain failure that will match snippet #1.
    memory.record_failure(
        "Cauchy-Schwarz applied without finite second moment",
        "concluded inequality without verifying E[X^2]<inf",
        "missing finite second moment hypothesis",
        "verify finite moments before applying CS",
        domain="proof",
    )

    # 2. Seed a small corpus and retrieve.
    prove.ingest_proof_corpus(
        "manual",
        [
            {
                "problem_id": "cs_finite_moment",
                "statement": "Cauchy-Schwarz under finite second moment",
                "lexical_keywords": ["cauchy", "schwarz", "finite", "moment"],
                "semantic_keywords": ["inner product inequality", "moment hypothesis"],
                "reference_proof": "Verify E[X^2]<inf, E[Y^2]<inf, then apply CS.",
            }
        ],
    )
    skeletons = prove.retrieve_skeletons(
        "Bound the variance of X+Y using Cauchy-Schwarz",
        lexical_keywords=["cauchy", "schwarz"],
        semantic_keywords=["inner product inequality"],
        k=3,
    )
    assert skeletons[0]["problem_id"] == "cs_finite_moment"

    # 3. Capture proposition + register skeleton + register draft.
    prop = prove.propose_proposition(
        "Var(X+Y) is bounded by 4*max(Var X, Var Y) under finite second moments"
    )
    skel = prove.propose_proof_skeleton(
        prop["node_id"],
        "Step 1 verify finite moments. Step 2 apply CS. Step 3 conclude.",
    )
    draft = prove.register_proof_draft(
        skel["node_id"],
        "Apply Cauchy-Schwarz: E[XY]^2 <= E[X^2] E[Y^2]. Conclude Var bound.",
    )

    # 4. Segment + diagnose + register + finalize.
    seg = prove.segment_proof(
        draft["node_id"],
        [
            "Apply Cauchy-Schwarz: E[XY]^2 <= E[X^2] E[Y^2].",
            "Therefore Var(X+Y) <= 4 max(Var X, Var Y).",
        ],
    )
    diag = prove.diagnose_snippet(seg["snippet_ids"][0])
    assert any(c["domain"] == "proof" for c in diag["candidates"])
    prove.register_diagnosis(
        seg["manifest_id"],
        seg["snippet_ids"][0],
        is_flawed=True,
        description="missing finite second moment check",
        matched_failure_ids=[c["failure_id"] for c in diag["candidates"][:1]],
    )
    prove.register_diagnosis(
        seg["manifest_id"],
        seg["snippet_ids"][1],
        is_flawed=False,
        description="conclusion ok",
    )
    fin = prove.finalize_manifest(seg["manifest_id"])
    assert fin["status"] == "open"
    assert fin["flawed_count"] == 1

    # 5. Compose + apply correction.
    prompt = prove.compose_correction_prompt(draft["node_id"], seg["manifest_id"])
    assert "missing finite second moment" in prompt["prompt"]
    corrected_text = (
        "Step 1: verify E[X^2]<inf and E[Y^2]<inf. "
        "Step 2: apply Cauchy-Schwarz E[XY]^2 <= E[X^2] E[Y^2]. "
        "Step 3: conclude Var(X+Y) <= 4 max(Var X, Var Y)."
    )
    out = prove.apply_correction(
        draft["node_id"], seg["manifest_id"], corrected_text, note="fix CS"
    )
    assert out["manifest_status"] == "applied"

    # 6. Audit: corrected draft is a child of the original draft.
    con = db._connect()
    try:
        new_node = con.execute(
            "SELECT parent_id, text FROM mem_nodes WHERE node_id = ?",
            (out["new_draft_id"],),
        ).fetchone()
    finally:
        con.close()
    assert new_node["parent_id"] == draft["node_id"]
    assert "verify E[X^2]" in new_node["text"]

    manifests = prove.list_diagnostic_manifests(draft_id=draft["node_id"])
    assert len(manifests) == 1
    assert manifests[0]["status"] == "applied"
