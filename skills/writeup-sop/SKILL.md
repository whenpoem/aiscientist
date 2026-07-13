---
name: writeup-sop
description: Produce or revise research reports, result-bearing Markdown, paper sections, and manuscripts without overstating evidence. Use whenever writing text that reports experimental metrics, statistical conclusions, hypothesis rankings, theorem claims, or research findings. Do not trigger for ordinary README edits, changelogs, or prose with no research-result claim.
---

# Write-up SOP

This is an agent-gated publication workflow, not a filesystem security
boundary. Hooks block only a narrower set of obvious unsafe writes.

## Inputs and final deliverables

Require the target audience/venue, output path and format, intended claims,
linked hypothesis/proposition ids, metric pins, and whether each result is
confirmatory or exploratory. Deliver the manuscript/report, a claim manifest,
reviewer JSON, and a short list of unresolved limitations.

## 1. Build the claim manifest before drafting

List every meaningful claim with:

- exact intended wording;
- kind: `result_metric`, `statistical_claim`, `context`, or `theorem`;
- role: central, supporting, or background;
- mode: confirmatory, exploratory, or not applicable;
- linked hypothesis/proposition id;
- required evidence and current status.

Dates, versions, seed counts, baseline counts, model sizes, and timeouts are
usually context. They must be accurate but are not automatic provenance gates.

## 2. Close the empirical evidence chain

For each publication-critical numeric or statistical claim:

1. Call `mcp__verify__check_provenance`. Missing provenance means rerun,
   remove the claim, or clearly downgrade it to exploratory.
2. Require a real `pin_id` for central metrics.
3. Call `mcp__verify__refresh_claim`. Any stale code, data, config, Git state,
   dependency lock, runtime, or tracked environment blocks the central claim.
   Legacy `unchecked` evidence must be disclosed and is insufficient as the
   only support for a headline result.
4. Require a current stable seed verdict for central experimental metrics, or
   narrow the wording to an unstable/exploratory observation.
5. For method-versus-baseline claims, require a fair `baseline_fairness`
   verdict or disclose the resource mismatch next to the comparison.
6. For confirmatory claims, require the matching preregistration to be `met`.
   Check its fixed `family_id` and `family_size`; an open or missed row blocks
   confirmatory wording.

Never convert an observed exploratory run into a confirmatory claim after the
fact.

## 3. Describe BT rankings honestly

When rankings matter, report strength, comparison count, and uncertainty only
as a joint batch MAP Bradley-Terry result. The compatibility fields `lcb` and
`ucb` are uncalibrated approximate posterior intervals. Do not call them strict
95% confidence intervals, and do not use overlap/non-overlap as proof that one
hypothesis is truly superior.

## 4. Close theorem and proof claims

For every theorem, lemma, proposition, corollary, or "we prove" statement:

1. link a real proposition node;
2. find the latest proof draft and diagnostic manifest;
3. require the final manifest to be `empty`; an `open` manifest blocks writing;
4. cite a verified Lean attempt when available;
5. when Lean verification is absent, add an explicit `unverified` annotation
   and state what evidence the natural-language proof has received;
6. refresh any provenance-backed references used in the proof.

Use `$prove-sop` to repair missing proof evidence before continuing.

## 5. Draft with evidence-local wording

Write each central claim close to its scope, metric definition, uncertainty,
dataset, baseline conditions, and limitation. Keep exploratory language
visibly distinct from confirmatory language. Do not bury failed preregistration,
unstable seeds, stale evidence, or resource imbalance in an appendix.

A useful report order is:

1. question and contribution;
2. related evidence and gap;
3. method and preregistered/exploratory status;
4. experiment and run-manifest details;
5. results as findings, not table narration;
6. verification, failures, and robustness;
7. proof evidence when applicable;
8. limitations and conclusion.

## 6. Run the adversarial reviewer

Use the reviewer role when available; otherwise apply its checklist inline.
The required JSON keys are:

- `verdict`: `accept`, `revise`, or `reject`;
- `numeric_claims`;
- `theorem_claims`;
- `provenance_trace`;
- `blockers`;
- `notes`.

`accept` is forbidden when `blockers` is non-empty, a central numeric claim
lacks a pin, central evidence is stale, a confirmatory preregistration is not
met, a theorem manifest is open, or an unformalized theorem lacks an explicit
unverified flag.

## 7. Respond to the verdict

- `accept`: write/finalize the requested artifact and optionally export a
  closure report.
- `revise`: address every blocker, refresh the claim manifest, and rerun the
  reviewer. Do not silently weaken checks.
- `reject`: do not publish through this workflow. Return the blocking evidence
  and the minimum rerun/removal needed for reconsideration.

## Completion criteria

The write-up is complete only when every central claim maps to fresh evidence,
exploratory and confirmatory wording is accurate, statistical uncertainty is
described with its real calibration status, theorem claims pass the proof
branch or are explicitly unverified, reviewer JSON is complete, and the final
artifact contains no unresolved blocker disguised as prose.
