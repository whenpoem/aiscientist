---
name: research-sop
description: Run an end-to-end, auditable research workflow from question framing through literature, competing hypotheses, experiment selection, implementation, verification, and claim handoff. Use whenever the user asks to investigate, compare, test, validate, or establish an empirical research claim, including when they do not explicitly call it research. Do not use for a simple factual lookup or a narrowly scoped code change with no research claim.
---

# Research SOP

Use this skill as the main router for empirical research. Custom `researcher`,
`engineer`, `verifier`, `reviewer`, and `budgeter` agents are optional helpers;
when they are unavailable, execute the same role boundaries inline.

## Inputs and promised output

Before doing expensive work, establish:

- the research question and decision the result should support;
- the active workspace and relevant files or datasets;
- whether the work is exploratory or confirmatory;
- cost, time, reserved-data, and external-service constraints;
- whether the user asked only for diagnosis or also authorized implementation.

Finish with a research handoff containing the question, literature basis,
hypothesis node ids, comparison evidence, experiment manifest, verification
status, unresolved risks, and the next justified action. Do not call a result
publication-ready merely because code ran or unit tests passed.

## 1. Orient and resume

1. If Cockpit is useful, tell the user how to start it from the same workspace:
   `claudescientist cockpit --workspace <path> --lang zh`.
2. Inspect the active frontier and ancestors. Reuse an existing question or
   hypothesis when it already represents the task; otherwise create the
   question and candidate hypothesis nodes.
3. Call `mcp__memory__match_signatures` with the task and likely failure modes.
   Read matching failures before choosing a method.
4. Query existing literature and contradictions. Record a snapshot before a
   risky pruning decision or when resuming an interrupted investigation.

Expected state: a question node or explicit task statement, known prior
failures, and a short list of missing evidence.

## 2. Establish the evidence base

1. Call `mcp__memory__query_literature`, `find_baselines_for`, and
   `find_contradictions` as relevant.
2. Use arXiv or OpenAlex only when those optional MCPs are available. If they
   are absent, continue with repository sources and say what literature search
   remains incomplete; do not invent citations.
3. Ingest structured paper summaries that materially affect the decision.
4. Separate established facts, reported claims, assumptions, and open gaps.

Pause for user direction when the research question can be interpreted in
materially different ways or when the required data/source is unavailable.

Expected state: a concise evidence table and a defensible gap statement.

## 3. Generate comparable hypotheses

Create 3-5 falsifiable candidates when the question genuinely has competing
explanations. Each candidate needs:

- a `mem_nodes` hypothesis id and one-sentence statement;
- mechanism or rationale;
- expected observation and a result that would refute it;
- feasible experiment and cost estimate;
- known supporting and contradicting evidence.

Do not pad the list with paraphrases. With only one credible candidate, state
that limitation and skip the tournament.

## 4. Select without overstating uncertainty

When at least three candidates compete, run `$bt-tournament`. The current
leaderboard is a joint batch MAP Bradley-Terry fit. Its `lcb` and `ucb` fields
are retained for compatibility but represent an uncalibrated approximate
posterior interval, not a guaranteed 95% confidence interval.
Always surface the returned `interval_calibrated=False` flag in a handoff.
The underlying loop is `mcp__memory__judge_hypotheses` followed by
`mcp__memory__record_judgement`, then
`mcp__memory__get_bt_leaderboard`; keep those calls auditable even when the
Skill performs the routing.

Use comparisons to organize judgment, not manufacture certainty. Stop when
every serious candidate has enough direct evidence for a decision, the ranking
is stable to reasonable judging criteria, the budget is exhausted, or the user
chooses. Record the chosen path and why the alternatives were deferred. A
pause suggestion is advisory unless explicit auto-prune is enabled.

Expected state: selected hypothesis ids, comparison counts, approximate
intervals with the calibration caveat, and a recorded selection rationale.

## 5. Choose exploratory or confirmatory mode

Exploratory mode may prototype, inspect outcomes, and pin results, but every
claim stays labelled exploratory.

Confirmatory mode must lock the target before observing the confirmatory run:

1. Invoke `$preregister`.
2. Define `family_id` and fixed `family_size` for related tests before the
   first family member is resolved.
3. Lock metric, direction, threshold, alpha, seed count, and optional reserved
   dataset.
4. Pass every `prereg_id` into later experiment and verification records.

Never retroactively call an observed exploratory result confirmatory.

## 6. Plan and implement the experiment

1. Check configured budgets before expensive, remote, reserved-data, or long
   proof work. Missing budget configuration is advisory for low-cost work and
   a reason to ask before material cost.
2. Run `leakage_check` before training or evaluation code touches data splits.
3. Specify baselines, metrics, seeds, config files, input files, and the exact
   command before execution.
4. Implement only within the user's authorization. Preserve diagnosis-only
   boundaries when the user did not request a fix.
5. Record failures through `record_failure`; do not silently switch methods
   after a failed run.
6. Record and pin central metrics. v5.1 automatically attaches a run manifest
   containing experiment code, inputs, configs, lockfiles, Git state, command,
   seeds, runtime, and safe environment fields. Still pass `input_files` and
   `config_files` explicitly so domain data is complete.

Expected state: reproducible command, code/config/data fingerprints, results,
budget use, and failure records.

## 7. Verify independently

Treat verification as a separate role even when performed by the same host:

1. Check provenance and call `refresh_claim`; stale central evidence blocks
   promotion.
2. Re-run or inspect leakage checks.
3. Use `seed_perturb` for central experimental metrics and link the run to the
   metric pin. An unstable result must be narrowed or remain exploratory.
4. Run `baseline_fairness` for method-versus-baseline claims.
5. Access sequestered data only through `query_heldout`; budget is reserved
   before execution.
6. Resolve confirmatory preregistrations. A missed or open target cannot be
   rewritten as met.

Expected state: pin ids, fresh run manifests, seed verdict, fairness verdict,
reserved-data audit, and preregistration status.

## 8. Review and hand off to writing

Invoke `$writeup-sop` only after the claim inventory is ready. Publication-
critical claims require reviewer JSON with `verdict="accept"`; a non-empty
blocker list means revise or reject. Theorem-shaped claims also invoke
`$prove-sop` and its diagnostic/formalization checks.

## Failure and recovery paths

- Literature insufficient: report searched sources and missing access; keep
  hypotheses provisional.
- No reproducible baseline: stop comparative claims and record the blocker.
- Experiment fails: use `$debug-sop`, record the failure, then resume here from
  the last valid checkpoint.
- Budget exhausted: preserve state and offer a lower-cost next experiment.
- Verification fails or evidence is stale: do not write the central claim;
  rerun, narrow, downgrade to exploratory, or remove it.
- Interrupted work: inspect the graph, latest snapshot, preregistrations,
  pins, and manifests; do not restart from memory alone.

## Completion criteria

The research loop is complete only when the chosen hypothesis and alternatives
are traceable, experiment inputs and environment are fingerprinted, central
metrics have fresh provenance, required seed/fairness/preregistration checks
have explicit verdicts, failures and caveats are recorded, and the final claim
language matches the strength of that evidence.
