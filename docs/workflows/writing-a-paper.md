# Walkthrough: Writing a Paper

> 中文版本: [writing-a-paper.zh-CN.md](writing-a-paper.zh-CN.md)
> How to use the verification stack to draft a manuscript whose every numeric claim is traceable. Read [`first-research-task.md`](first-research-task.md) first if you have not yet — this walkthrough assumes you already have experiments and pinned metrics.

The `reviewer` agent enforces a strict contract: every numeric claim that ends up in a `.md` file must trace back to four anchors. This document explains how to satisfy that contract end to end.

## The four anchors

Before you start writing, internalize what the reviewer will demand for each number:

1. **Pinned metric** — there must be a `ver_metric_pins` row whose `claim` matches the number you cite
2. **Stable seed verdict** — `ver_seed_runs.verdict='stable'` for the linked metric pin
3. **Met preregistration** — a `ver_preregistrations` row with `status='met'`
4. **Fresh provenance** — `refresh_claim` reports `status='fresh'`, no drifted input files

If any one of the four is missing or stale, the reviewer refuses to draft and lists the missing anchor. This is a feature, not friction.

## Step 0: take a snapshot

Before any writing begins, freeze the state:

```
mcp__memory__snapshot label="paper-draft-v1"
```

This captures the entire hypothesis graph and BT ratings. If a reviewer ever questions a claim later, you can replay the exact state at writing time.

## Step 1: enumerate the claims

Open a fresh markdown file and list every numeric claim you intend to make:

```
- ViT-S/16 with per-head dropout 0.3 reaches 87.3% on CIFAR-10
- Without dropout, baseline reaches 85.5%
- Improvement is 1.8 percentage points
- Result is stable across seeds [0,1,2] (std=0.004)
- Comparison is fair under matched epoch budget (proposed=20, baseline=18)
```

This is the **claim manifest**. Each line corresponds to one anchor check.

## Step 2: invoke the writeup SOP

Run:

```
/writeup-sop draft a one-page report on the dropout investigation
```

This kicks off the workflow that will:

1. Iterate over the claim manifest
2. For each numeric claim, call `mcp__verify__check_provenance(claim)`
3. If status is `missing`, pause and ask you to either re-run the experiment or remove the claim
4. If status is `found`, also call `refresh_claim(claim)` to detect upstream drift
5. If everything passes, draft the surrounding prose

You will see the workflow halt visibly on any unverified number. This is correct behavior.

## Step 3: handle missing anchors

For each blocker the reviewer reports:

### "Missing pin"

The number is not pinned. Pin it:

```
mcp__verify__pin_metric claim="vit_dropout_test_accuracy" value=0.873 session_id=<auto> source_command="..."
```

### "Missing seed verdict"

The metric is pinned but no seed perturbation has been run. Run it:

```
mcp__verify__seed_perturb script_path=<your_script>.py seeds=[0,1,2] metric_pin_id=<the pin from above>
```

### "Missing or unmet preregistration"

The number was produced without being preregistered. There is no shortcut here — preregistration must happen *before* the experiment. The honest path is to:

1. Acknowledge in the manuscript that the result is exploratory, not confirmatory
2. Preregister now and **rerun** the experiment with fresh seeds
3. Cite the rerun result, not the original

This is exactly the line between exploratory and confirmatory analysis that the project enforces.

### "Stale provenance"

`refresh_claim` reports `status='stale'`. One or more input files has changed since the experiment ran. Either:

1. Restore the original files (best if drift was unintentional), or
2. Rerun the experiment against the current files and update the pin

The reviewer will not accept stale claims.

## Step 4: include the audit trail

For each claim that survives, the writeup workflow appends a hidden HTML comment with the trace:

```markdown
<!-- prov: pin_id=42 prereg_id=preg_8a3f seed_run_id=17 fresh=true snapshot=snap_2026-05-03 -->
The ViT-S/16 model with per-head dropout 0.3 reaches 87.3% on CIFAR-10.
```

These comments are invisible in rendered Markdown but serve as the audit trail. They are removed only at the final publish step, after a human review.

## Step 5: consider the contradictions

Before publishing, run:

```
mcp__memory__find_contradictions
```

This surfaces any pair of nodes connected by a `contradicts` edge. If a current claim contradicts an earlier one, the manuscript must either:

1. Resolve the contradiction explicitly in the prose, or
2. Mark the earlier claim as superseded and rerun any analysis that depended on it

## Step 6: handle the baseline

If the paper compares a proposed method to a baseline, include the fairness check:

```
mcp__verify__baseline_fairness proposed_log=runs/proposed.log baseline_log=runs/baseline.log
```

If the verdict is `unfair`, the writeup workflow will refuse to publish the comparison until either:

1. The baseline is re-run with matched budget, or
2. The unfair axes are explicitly disclosed in the manuscript

Disclosure is acceptable but rarely sufficient for top venues — better to match the budget.

## Step 7: final reviewer pass

Type:

```
@reviewer perform a final audit of the dropout writeup
```

The reviewer reads the entire draft and produces one of two outcomes:

- **`accept`** with a short summary of the verified anchors
- **`reject`** with a list of remaining blockers

You can iterate on `reject` outcomes by addressing each blocker, then re-running. The reviewer is intentionally pedantic; treat it as a peer reviewer, not a rubber stamp.

## What you should never do

These are explicit anti-patterns the system tries to make hard:

- **Cherry-pick seeds.** If only seed 1 of 3 hit the target, the verdict is `unstable` and the claim cannot pass.
- **Update a threshold after seeing results.** Preregistration thresholds are immutable. Filing a new preregistration with a looser threshold is allowed but must be disclosed.
- **Cite a number without `pin_metric`.** Even if the number is "obviously right", it must be pinned.
- **Bypass `query_heldout`.** Never read the held-out test set directly. The leakage guard will block it; the workflow will not.
- **Edit `.research-agent/state.db` by hand.** All state must go through the MCP tools. Manual edits leave audit gaps.

## A note on style

The project does not opine on prose style. It only enforces traceability. Once every number passes the four-anchor check, you are free to write in whatever voice you prefer — the system is silent on everything that is not a number.
