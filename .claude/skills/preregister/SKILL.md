---
name: preregister
description: Lock the falsification target for a confirmatory hypothesis before promoting results to main claims. Records metric, direction, threshold, multiple-comparison correction, and seed budget into ver_preregistrations.
---

# Preregister

This skill supports "decide before observing" for confirmatory claims. Exploratory runs may still use seed_perturb / pin_metric, but any number intended as a main publication claim should have a matching prereg row first.

## When to invoke

- Before a result is promoted from exploratory to a confirmatory manuscript claim.
- Right after `bt-tournament` returns the top-2 hypotheses when the next run is explicitly confirmatory.
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

1. Call `mcp__verify__list_preregistrations(hypothesis_id=...)`. If a row exists with status `open`, do not fail the session. Ask whether to reuse that lock, withdraw it outside this tool, or create a separate confirmatory prereg for a genuinely different metric.
2. Call `mcp__verify__preregister(...)` with the exact metric text and threshold.
3. Surface the resulting `prereg_id` in the cockpit `Claims` tab; the user must see it before the engineer starts implementing.
4. Pass `prereg_id` along the agent chain so `engineer` knows which lock applies.

## Resolution

The engineer or verifier later calls `mcp__verify__resolve_preregistration(prereg_id, observed_value, observed_p_value)`. The verdict is **frozen** at that point and:

- BH / Bonferroni correction is applied across all currently-open rows (so locking many preregs at once intentionally tightens alpha).
- `prereg_resolved` events fire into the cockpit.
- The `reviewer` agent later treats confirmatory manuscript claims with status != `met` as blockers. Exploratory claims must be labelled as exploratory in the manuscript.

## Guardrails

- Never edit a prereg after lock. There is no `update_preregistration`. If the locking was wrong, file a new prereg and add a note in the manuscript explaining that the earlier run was exploratory or superseded.
- `withdrawn` is reserved for cases the user actively cancels a hypothesis; the verifier never withdraws on its own.
- Do not invoke this skill in parallel with a confirmatory seed_perturb. Exploratory seed_perturb runs may exist before the lock, but must stay labelled exploratory.
