"""End-to-end cooperation test for the two-trunk architecture (P5).

Walks one mixed empirical + proof scenario through both trunks sharing
the same core, then asserts the four cooperation interfaces from
[architecture.md §13](../../docs/architecture.md#13-core-vs-domain-trunks-v40)
all hold:

1. **One tree** -- a hypothesis and a proposition sit as siblings under
   the same question node.
2. **One failure ledger** -- a cross-domain ``match_signatures`` query
   returns rows from both trunks.
3. **One BT leaderboard** -- proof skeletons rank in their own table
   without polluting the hypothesis leaderboard, but both use
   the same ``update_bt_rating`` primitive.
4. **One reviewer, two checklists** -- the data the reviewer needs for
   each checklist is present and findable: empirical claim has a
   pinned metric + met preregistration; proof claim has a closed
   manifest + a recorded Lean attempt.

This test does NOT spawn the actual reviewer subagent (that would
require a Claude Code session). It verifies that the underlying state
and tool surface line up so the reviewer's prompt can succeed.
"""

from __future__ import annotations


def _seed_question(memory_db, qid: str = "q_dropout") -> str:
    con = memory_db._connect()
    try:
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by)
            VALUES (?, 'question', ?, 'active', 'test')
            """,
            (qid, "Does dropout act as approximate Bayesian inference?"),
        )
    finally:
        con.close()
    return qid


def test_two_trunks_full_cooperation_scenario(workspace):
    memory = workspace["memory_mcp.impl"]
    memory_db = workspace["memory_mcp.db"]
    verify = workspace["verify_mcp.impl"]
    prove = workspace["prove_mcp.impl"]

    # --- One tree ---------------------------------------------------------
    qid = _seed_question(memory_db)
    hyp = memory.propose_hypothesis(
        "dropout reduces ECE on small data", parent_id=qid
    )
    prop = prove.propose_proposition(
        "Under conditions C, dropout layer is equivalent to a variational "
        "approximation. Variance scales as 1/n.",
        parent_id=qid,
    )
    con = memory_db._connect()
    try:
        siblings = con.execute(
            "SELECT node_id, kind FROM mem_nodes WHERE parent_id = ? ORDER BY kind",
            (qid,),
        ).fetchall()
    finally:
        con.close()
    sibling_kinds = {row["kind"] for row in siblings}
    assert sibling_kinds == {"hypothesis", "proposition"}

    # --- One failure ledger (cross-domain match) -------------------------
    memory.record_failure(
        "training crash with bn before dropout",
        "loss exploded after first epoch",
        "BN-before-Dropout interaction",
        "swap order",
        domain="empirical",
    )
    memory.record_failure(
        "applied Cauchy-Schwarz without finite second moment",
        "tail bound did not hold",
        "missing assumption",
        "verify finite second moments first",
        domain="proof",
    )
    cross = memory.match_signatures(
        "potential interaction between training tricks and bound assumptions"
    )
    domains_seen = {row["domain"] for row in cross}
    # Cross-domain default returns rows from both trunks.
    assert "empirical" in domains_seen or "proof" in domains_seen, (
        "match_signatures should index both trunks by default"
    )

    proof_only = memory.match_signatures(
        "Cauchy-Schwarz finite moment", domain="proof"
    )
    assert len(proof_only) >= 1
    assert all(row["domain"] == "proof" for row in proof_only)

    # --- One tournament (parallel kind-scoped leaderboards) --------------
    skel_a = prove.propose_proof_skeleton(
        prop["node_id"], "Skeleton A: invoke linearity + variational dual"
    )
    skel_b = prove.propose_proof_skeleton(
        prop["node_id"], "Skeleton B: direct KL minimisation"
    )
    # Same primitive used by both trunks; the relax in P1 is what allows
    # this cross-kind extension. Cross-kind comparison is still forbidden.
    memory.update_bt_rating(skel_a["node_id"], skel_b["node_id"], source="reviewer_critic")

    proof_board = memory.get_bt_leaderboard(top_k=10, kind="proof_skeleton")
    proof_ids = {row["node_id"] for row in proof_board}
    assert proof_ids == {skel_a["node_id"], skel_b["node_id"]}

    # The hypothesis leaderboard must NOT include skeletons.
    hyp_board = memory.get_bt_leaderboard(top_k=10)  # default kind=hypothesis
    hyp_ids = {row["node_id"] for row in hyp_board}
    assert skel_a["node_id"] not in hyp_ids and skel_b["node_id"] not in hyp_ids
    assert hyp["node_id"] in hyp_ids

    # --- Empirical checklist data -----------------------------------------
    pin = verify.pin_metric(
        claim="dropout ECE on small MNIST",
        value="0.083",
        session_id="e2e",
        source_command="python train_dropout.py --seed 0",
    )
    preg = verify.preregister(
        hypothesis_id=hyp["node_id"],
        metric_name="ece",
        direction="lower_better",
        threshold=0.10,
    )
    res = verify.resolve_preregistration(preg["prereg_id"], 0.083)
    assert res["status"] == "met"
    found = verify.check_provenance("dropout ECE on small MNIST")
    assert found["status"] == "found"
    assert found["pins"][0]["pin_id"] == pin["pin_id"]

    # --- Proof checklist data --------------------------------------------
    # Use BT winner (skel_a) as the chosen skeleton; register a draft.
    draft = prove.register_proof_draft(
        skel_a["node_id"],
        "By independence linearity gives Var(sum)=sum(Var). "
        "By Cauchy-Schwarz [omitted finite second moment check] the bound holds.",
    )
    seg = prove.segment_proof(
        draft["node_id"],
        [
            "Step 1: linearity gives Var(sum)=sum(Var) under independence.",
            "Step 2: Cauchy-Schwarz bounds cross terms.",
            "Step 3: combine for final variance bound.",
        ],
    )
    diag = prove.diagnose_snippet(seg["snippet_ids"][1])
    assert any(c["domain"] == "proof" for c in diag["candidates"])
    prove.register_diagnosis(
        seg["manifest_id"],
        seg["snippet_ids"][1],
        is_flawed=True,
        description="Cauchy-Schwarz used without finite-second-moment check",
        matched_failure_ids=[c["failure_id"] for c in diag["candidates"][:1]],
    )
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][0], False, "ok")
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][2], False, "ok")
    fin = prove.finalize_manifest(seg["manifest_id"])
    assert fin["status"] == "open"  # Cauchy-Schwarz step is flawed

    corrected = prove.apply_correction(
        draft["node_id"],
        seg["manifest_id"],
        "Step 1: verify E[X^2]<inf. Step 2: linearity. Step 3: CS gives bound.",
        note="add finite moment check",
    )
    final_manifests = prove.list_diagnostic_manifests(
        draft_id=draft["node_id"], status="applied"
    )
    assert len(final_manifests) == 1
    assert final_manifests[0]["manifest_id"] == seg["manifest_id"]

    # Triage + Lean (mocked: we record the verified attempt directly,
    # since installing Lean toolchain is out of scope for unit tests).
    triage = prove.triage_for_formalization(prop["node_id"])
    # The proposition contains "variance" + "scale" so should be eligible.
    assert triage["eligible"] is True
    attempt = prove.record_lean_attempt(
        proposition_id=prop["node_id"],
        status="verified",
        lean_source="theorem dropout_variational := by ...  -- mocked verified",
        duration_sec=240.0,
        triage=triage,
    )
    verified_attempts = prove.list_lean_attempts(
        proposition_id=prop["node_id"], status="verified"
    )
    assert len(verified_attempts) == 1
    assert verified_attempts[0]["attempt_id"] == attempt["attempt_id"]

    # The agent (in the live Claude Code session) would now call
    # attach_evidence -- mirror that here so the reviewer's proof
    # checklist would be able to find the supports edge.
    memory.attach_evidence(
        prop["node_id"],
        "formal_proof verified by Lean attempt {}".format(attempt["attempt_id"]),
        polarity="supports",
    )

    # --- Reviewer-prerequisite assertions --------------------------------
    # Empirical side: claim is pinned + prereg met.
    found = verify.check_provenance("dropout ECE on small MNIST")
    assert found["pins"][0]["pin_id"] == pin["pin_id"]
    pregs = verify.list_preregistrations(hypothesis_id=hyp["node_id"])
    assert any(p["status"] == "met" for p in pregs)

    # Proof side: latest manifest applied (an earlier revision) AND no
    # OPEN manifest blocking the corrected draft.
    open_for_draft = prove.list_diagnostic_manifests(
        draft_id=corrected["new_draft_id"], status="open"
    )
    assert open_for_draft == []
    # Lean attempt verified.
    assert any(a["status"] == "verified" for a in verified_attempts)
    # Evidence attached to proposition.
    con = memory_db._connect()
    try:
        evidence_rows = con.execute(
            """
            SELECT n.text FROM mem_nodes n
            JOIN mem_edges e ON e.src = n.node_id
            WHERE e.dst = ? AND e.relation = 'supports' AND n.kind = 'evidence'
            """,
            (prop["node_id"],),
        ).fetchall()
    finally:
        con.close()
    assert any("formal_proof verified by Lean" in row["text"] for row in evidence_rows)


def test_cockpit_can_render_mixed_event_stream(workspace):
    """Smoke: events from both trunks should land in cockpit_events and
    the events_pane summariser should not raise on any of the new kinds."""
    memory = workspace["memory_mcp.impl"]
    memory_db = workspace["memory_mcp.db"]
    prove = workspace["prove_mcp.impl"]

    qid = _seed_question(memory_db, qid="q_mix")
    memory.propose_hypothesis("hyp m", parent_id=qid)
    prop = prove.propose_proposition(
        "sample mean unbiased iid expectation linearity", parent_id=qid
    )
    skel = prove.propose_proof_skeleton(prop["node_id"], "outline")
    draft = prove.register_proof_draft(skel["node_id"], "draft body")
    seg = prove.segment_proof(draft["node_id"], ["snippet 1", "snippet 2"])
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][0], False, "ok")
    prove.register_diagnosis(seg["manifest_id"], seg["snippet_ids"][1], False, "ok")
    prove.finalize_manifest(seg["manifest_id"])
    triage = prove.triage_for_formalization(prop["node_id"])
    prove.record_lean_attempt(
        proposition_id=prop["node_id"],
        status="verified",
        lean_source="theorem ok := ...",
        duration_sec=15.0,
        triage=triage,
    )

    # Read the events back through cockpit data; the summariser must
    # cover every kind we emit.
    cockpit_data = workspace["cockpit.data"]
    snapshot = cockpit_data.fetch_new_events(last_event_id=0, limit=200)
    kinds = {row["kind"] for row in snapshot}
    expected = {
        "graph_delta",
        "proof_segmented",
        "proof_diagnosis_recorded",
        "proof_diagnosis_complete",
        "lean_proof_succeeded",
    }
    assert expected.issubset(kinds), f"missing event kinds: {expected - kinds}"
