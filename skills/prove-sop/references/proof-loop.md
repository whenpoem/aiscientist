# Proof loop reference

## Contents

1. Capture and retrieve
2. Select a skeleton
3. Draft and diagnose
4. Correct
5. Add optional evidence
6. Review and deliver

## 1. Capture and retrieve

If needed, call `mcp__prove__propose_proposition` and attach the proposition to
the related question or hypothesis with `parent_id`. Extract lexical and semantic
keywords, then call `mcp__prove__retrieve_skeletons`. If the corpus offers fewer
than three relevant candidates, ingest appropriate source material or create
from-scratch outlines; do not pad the tournament with irrelevant candidates.

## 2. Select a skeleton

Register retrieved candidates and two or three materially different original
outlines with `mcp__prove__propose_proof_skeleton`. Use `$bt-tournament` for
same-kind pairwise judgments and inspect
`mcp__memory__get_bt_leaderboard(kind="proof_skeleton")`.

Choose only after every viable candidate has meaningful comparison coverage,
the leading choice remains stable under reasonable additional comparisons, and
the proof plan itself satisfies the proposition's assumptions. The `lcb` and
`ucb` fields are compatibility names for uncalibrated Laplace-MAP summaries;
their separation alone is neither a significance result nor a stopping rule.
Optionally narrate the selection rationale to Cockpit.

## 3. Draft and diagnose

Generate the proof from the proposition and chosen skeleton, then persist it with
`mcp__prove__register_proof_draft`. Split the draft into minimal non-trivial
logical units and call `mcp__prove__segment_proof`.

For every snippet:

1. Call `mcp__prove__diagnose_snippet` for relevant historical failure patterns.
2. Independently decide whether the step is valid under the stated assumptions.
3. Persist the decision with `mcp__prove__register_diagnosis`.

Call `mcp__prove__finalize_manifest` only after every snippet has a recorded
diagnosis.

## 4. Correct

If the manifest remains open, call `mcp__prove__compose_correction_prompt`, make
the smallest global correction that repairs all recorded flaws, and persist it
with `mcp__prove__apply_correction`. Segment and diagnose the returned draft id
from scratch. Repeat until the latest manifest is empty or a genuine unresolved
limitation must be reported. Optionally narrate major correction choices.

## 5. Add optional evidence

When a theorem depends on an empirically uncertain constant, route that claim
through `$preregister`, run the confirmatory experiment, and link the resulting
evidence without presenting it as a proof of unrelated mathematical steps.

For a small, closed, mathlib-friendly lemma, call
`mcp__prove__triage_for_formalization`. Before attempts expected to last at least
five minutes, call `mcp__verify__budget_check`; after the attempt, call
`mcp__verify__budget_consume` with actual duration. Record success, failure, or
timeout. Feed reusable proof failures to
`mcp__memory__record_failure(domain="proof")`.

## 6. Review and deliver

Apply the reviewer proof checklist. The final output must identify the
proposition, assumptions, proof draft, latest manifest, corrections made, and
Lean status. A theorem without Lean verification must say `unverified`; do not
hide that status behind an empty diagnostic manifest.

If the proof cannot be closed, return the smallest unresolved claim, the failed
approaches and evidence, and the next action needed. Do not label an open proof
as complete.
