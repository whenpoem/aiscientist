---
name: prove-sop
description: End-to-end statistical proof loop. Use when the user asks to prove a statistical proposition, when a hypothesis is promoted to a theorem, or when the empirical trunk's reviewer demands a theorem-side gate. This SOP is suggestion-only (per ADR 0007); skip, loop, or interleave with empirical work as the situation calls for.
---

# Prove SOP

When the user asks for a statistical proof ("prove X", "show that Y holds", "give a rigorous derivation"), or when a `proposition` node sits without a verified proof:

1. **Memory lookup**: call `mcp__memory__match_signatures` with the proposition text and `domain="proof"`. If similar past proof errors exist, **read them first** before drafting.
2. **Capture the proposition**: if not already in the graph, call `mcp__prove__propose_proposition` to register it. Pass `parent_id` to a related question or hypothesis node so empirical and theoretical work share one tree (architecture.md §13).
3. **Skeleton retrieval**: call `mcp__prove__retrieve_skeletons` with lexical and semantic keywords you extracted from the proposition. If fewer than 3 candidates rank above similarity 0.4, ingest more material via `mcp__prove__ingest_proof_corpus` first or fall back to a from-scratch outline.
4. **Skeleton tournament**: from the retrieved candidates plus 2-3 of your own outline drafts, register them as siblings via `mcp__prove__propose_proof_skeleton`. Run `$bt-tournament` to BT-rank them; the proof-trunk leaderboard is `mcp__memory__get_bt_leaderboard(kind="proof_skeleton")`. Stop when the top-2 LCB / UCB intervals separate or 3 comparisons cover every candidate.
5. **Draft generation**: pick the BT winner. Read the proposition plus the selected skeleton, assemble the drafting prompt inline, and generate the LaTeX draft yourself (do not spawn a sub-agent for this). Persist it via `mcp__prove__register_proof_draft`. *At this branch point* (choosing one skeleton over the others), optionally call `mcp__cockpit__narrate("why this skeleton")` so the cockpit reflects the decision (v5.0; optional).
6. **Segment + diagnose**: split the draft into minimal logical units (~3-12 snippets per page; one per non-trivial step). Call `mcp__prove__segment_proof(draft_id, snippets)` -- this opens a fresh diagnostic manifest. For each snippet, call `mcp__prove__diagnose_snippet` to get historical proof-error candidates, decide `is_flawed`, and call `mcp__prove__register_diagnosis`. After all snippets are recorded, call `mcp__prove__finalize_manifest`.
7. **Correction (only if status='open')**: call `mcp__prove__compose_correction_prompt` to build the global-fix prompt; generate the corrected LaTeX inline; call `mcp__prove__apply_correction`. The new draft is itself segmentable -- if you suspect more flaws, loop back to step 6 on the new `draft_id`. *Before applying a global correction* (a non-trivial decision among possible fixes), optionally call `mcp__cockpit__narrate("...")` so the activity pane shows the reasoning (v5.0; optional).
8. **Empirical companion (optional, recommended for theorems with concrete constants)**: if the proof contains a numeric constant you only conjecture, hand off to the empirical trunk via `$preregister`. Lock metric, threshold, direction. The reviewer will later cross-link the theorem and the preregistration.
9. **Lean reinsurance (optional)**: when a key lemma is small + closed (single-page, mathlib-friendly), call `mcp__prove__triage_for_formalization`. If `eligible=True`, request a wallclock budget from the `budgeter` agent for long attempts (see [`prover.md` § Budget](../../agents/prover.md)); low-cost checks may proceed with an audit warning when no budget is configured. Then spawn the `prover` subagent. A successful `lean_verify` attaches as the strongest possible evidence; a failure feeds the cross-domain failure ledger via `mcp__memory__record_failure(domain="proof")`.
10. **Reviewer**: when the manuscript is ready to ship, the `reviewer` agent's proof checklist (P5) demands either a `manifest.status='empty'` plus a Lean verification, or an explicit `unverified` flag. Plan accordingly.

## Guardrails

- BT comparisons forbid cross-kind matches; do not use `update_bt_rating` between a hypothesis and a proof_skeleton. Use parallel tournaments (architecture.md §13). Stop a skeleton tournament when the top-2 LCB / UCB intervals separate, or when every candidate has participated in at least one comparison.
- `mcp__prove__diagnose_snippet` is read-only; you must explicitly `register_diagnosis` for the entry to land in the manifest. This is intentional: the LLM judgment lives in the agent loop, not the MCP tool.
- A manifest only finalises once. To re-segment a corrected draft, call `segment_proof` on the new `draft_id` -- this opens a fresh manifest. Old manifests stay around as audit history.
- Lean failures are not blockers. The proof trunk's first-class output is the NL draft; Lean is reinsurance.
- **Lean attempts ≥ 5 minutes should go through the `budgeter` agent** (`prover.md` § Budget). Missing budget context is an audit warning, not a reason to discard the NL proof.

## Cross-references

- Tool layering doctrine: [ADR 0007](../../docs/adr/0007-tools-skills-hooks-layering.md)
- Two-trunk architecture: [ADR 0008](../../docs/adr/0008-two-trunk-domain-architecture.md)
- Cooperation interfaces: [architecture.md §13](../../docs/architecture.md#13-core-vs-domain-trunks-v40)
- Empirical companion gate: `$preregister`
- Skeleton ranking: `$bt-tournament`
