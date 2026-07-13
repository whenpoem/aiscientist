# ADR 0004: Replace Elo with Bradley-Terry ranking

- **Status**: Accepted (v3.0), estimation method amended in v5.1
- **Date**: 2026-04

## Context

In v0.2 hypotheses were ranked with classical Elo (K=32) updated once per
`record_judgement` call. Two real-world friction points emerged:

1. **No confidence interval.** Elo gives a point estimate. We had no
   principled way to say "the top hypothesis is better than #2 with 95%
   confidence" or "this branch is far enough behind that we should pause
   it". The user's original brief in `创新点.md` flagged exactly this.
2. **Single-shot updates.** Elo's K-factor is a fixed step size that does
   not narrow as evidence accumulates. After 30 comparisons, Elo treats
   the next comparison the same as the first one.

For a research tournament where we want the system to **decide which
hypotheses to keep investigating**, neither of these is acceptable.
Bradley-Terry models hypothesis strength as a latent parameter `theta_i`
with a posterior whose variance shrinks as comparisons accumulate. That
shrinkage is exactly what a "pause low-strength branches" decision needs.

## Decision

> **v5.1 amendment:** the original per-comparison online update below proved
> order-dependent. Current code refits the complete comparison ledger with a
> joint Gaussian-prior MAP solve after every comparison and derives centred
> Laplace covariance from the full precision matrix. The compatibility names
> `lcb` / `ucb` now denote uncalibrated approximate posterior summaries, not
> frequentist confidence or strict LUCB bounds. The original text is retained
> here only as historical rationale.

Add a Bradley-Terry layer alongside (not replacing) the legacy Elo
columns:

- New table `mem_bt_ratings` carries `strength`, `strength_var`,
  `n_comparisons`, `status`. Initialised with `strength=0`,
  `strength_var=1.0` (Beta(1,1)-equivalent shrinkage prior).
- New table `mem_bt_comparisons` is an append-only ledger of every
  pairwise comparison applied.
- Joint full-ledger MAP refit via Newton solves with a zero-centred Gaussian
  prior. Strength is clipped to [-12, 12]; variance has a 1e-4 floor.
- Approximate posterior interval: `strength +/- z * sqrt(var)`. It is not a
  calibrated confidence interval or a significance test.
- `record_judgement` is the **only** dual-writer: it updates
  `mem_nodes.elo_score` AND calls `_bt_apply_comparison`. New code paths
  use `update_bt_rating`, which writes only the BT ledger but accepts a
  broader source set (`metric_diff`, `user_intervention`,
  `reviewer_critic`, `llm_judge`).
- `mem_nodes.elo_score` is kept as a read-only compatibility column.
- New tool `expected_information_gain` ranks candidate hypotheses by the
  predicted variance reduction from the next comparison.

The math is documented in [`docs/architecture.md`](../architecture.md)
section 6.2.

## Consequences

### Positive

- Order-invariant fits remove the recency effect that previously changed the
  winner when the same comparison multiset was inserted in another order.
- Variance shrinks as evidence accumulates; later comparisons cost less
  per bit of information.
- `expected_information_gain` makes "what should I compare next" a
  computable question, not a guess.
- v0.2 readers that look at `mem_nodes.elo_score` keep working.

### Negative

- Two ranking columns exist now. Discipline is required to keep new code
  reading `mem_bt_ratings.strength` instead of the legacy Elo.
- The Laplace approximation is only locally Gaussian; pathological
  comparison sequences (one hypothesis always wins) need the strength
  clip to stay well-defined.
- `_bt_apply_comparison` is a dual-write inside one transaction; partial
  failure of the second UPDATE leaves the comparison row referring to a
  non-updated rating. Acceptable at single-process scale; flagged in the
  v3.1 roadmap as something to harden if multi-session use lands.

### Alternatives considered

- **TrueSkill** - lost because it is over-parameterised for a single-rank
  tournament and the public Python implementations are heavy.
- **Bayesian Bradley-Terry with full MCMC** - remains deferred because a joint
  MAP refit is deterministic and cheap enough for the present tournament size.
- **Just bigger K-factor** - lost because the missing piece is
  uncertainty, not aggressiveness.

## References

- Originating discussion: [`docs/archive/plan-v3.0.md`](../archive/plan-v3.0.md)
  sections 1 and 4. User intent: [`docs/archive/original-ideas.zh-CN.md`](../archive/original-ideas.zh-CN.md).
- Math: Hunter (2004), "MM Algorithms for Generalized Bradley-Terry Models".
- Implementation: [`src/memory_mcp/tools/bt.py`](../../src/memory_mcp/tools/bt.py).
- Cross-component contract: [`docs/architecture.md`](../architecture.md) section 6.
