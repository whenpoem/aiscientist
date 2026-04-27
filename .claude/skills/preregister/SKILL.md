---
name: preregister
description: Lock the falsification target for a hypothesis BEFORE any experiment runs. Records metric, direction, threshold, multiple-comparison correction, and seed budget into ver_preregistrations. Required by V3.0 research-sop after the BT tournament selects a winner.
---

# Preregister

This skill enforces "decide before observing": the engineer cannot use seed_perturb / pin_metric to pin a number unless a matching prereg row exists.

## When to invoke

- Right after `bt-tournament` returns the top-2 hypotheses and BEFORE the engineer touches any code.
- Whenever the user types `/preregister`.

## Required arguments

| arg | meaning | example |
|---|---|---|
| `hypothesis_id` | id from `mem_nodes` (kind=hypothesis) | `hyp_a3f9...` |
| `metric_name` | exact claim text the engineer will pin later | `"test accuracy"` |
| `direction` | `higher_better` or `lower_better` | `higher_better` |
| `threshold` | number that separates `met` from `missed` | `0.85` |
| `seed_count` | how many seeds the seed_perturb call must use | `5` |
| `alpha` | nominal Type-I error rate | `0.05` |
| `mc_correction` | `bh` (Benjamini-Hochberg, default), `bonferroni`, or `none` | `bh` |
| `heldout_dataset` | optional dataset name to be queried via query_heldout | `mnist-test` |

## Workflow

1. Call `mcp__verify__list_preregistrations(hypothesis_id=...)`. If a row exists with status `open`, fail loudly: do not double-lock.
2. Call `mcp__verify__preregister(...)` with the exact metric text and threshold.
3. Surface the resulting `prereg_id` in the cockpit `Claims` tab; the user must see it before the engineer starts implementing.
4. Pass `prereg_id` along the agent chain so `engineer` knows which lock applies.

## Resolution

The engineer or verifier later calls `mcp__verify__resolve_preregistration(prereg_id, observed_value, observed_p_value)`. The verdict is **frozen** at that point and:

- BH / Bonferroni correction is applied across all currently-open rows (so locking many preregs at once intentionally tightens alpha).
- `prereg_resolved` events fire into the cockpit.
- The `reviewer` agent later refuses to accept any manuscript whose claims point to a prereg with status != `met`.

## Guardrails

- Never edit a prereg after lock. There is no `update_preregistration`. If the locking was wrong, file a new prereg with `mc_correction='none'` and add a note in the manuscript.
- `withdrawn` is reserved for cases the user actively cancels a hypothesis; the verifier never withdraws on its own.
- Do not invoke this skill in parallel with seed_perturb. Lock first, then run.
