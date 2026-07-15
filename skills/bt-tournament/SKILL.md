---
name: bt-tournament
description: Rank competing hypotheses or proof skeletons from the complete comparison ledger using a joint batch MAP Bradley-Terry fit and approximate posterior intervals. Use whenever 3 or more candidates compete for the next experiment, or when the user asks which branch currently leads. Do not present the intervals as calibrated confidence bounds.
---

# BT Tournament

This skill records pairwise judgments and refits the complete comparison ledger.
The `lcb` and `ucb` names are retained for compatibility, but they are 95%
*approximate posterior* intervals from a centered Laplace approximation. They
are not calibrated frequentist confidence intervals or strict LUCB bounds.

## When to invoke

- Researcher subagent has just emitted >= 3 hypothesis nodes in one turn.
- The user explicitly typed `/bt-tournament`.
- The cockpit shows candidates with unresolved approximate intervals and the user asks which to push first.

## Workflow

1. Gather the candidate hypothesis node ids and texts from `mcp__memory__get_active_frontier`.
2. For each pair you intend to compare, call `mcp__memory__judge_hypotheses` to fetch the canonical comparison prompt. Evaluate inline (do not spawn a sub-agent just to judge).
3. Decide a winner. Call `mcp__memory__record_judgement(a, b, winner, reason)`. Internally this records the comparison and updates the BT leaderboard; you do not need to call `update_bt_rating` separately.
4. Pull the leaderboard via `mcp__memory__get_bt_leaderboard(top_k=10)`. Look at
   `strength`, `probability_best`, `n_comparisons`, `fit_converged`, and
   `insufficient_samples`.
5. Compare the top two with `mcp__memory__compare_bt_candidates(top_id,
   runner_up_id)`. Stop when every serious candidate has at least 3 relevant
   comparisons and `probability_a_beats_b >= 0.95`. Also stop if the budget is
   exhausted or the user chooses. If `fit_converged` is false, do not use the
   posterior probability as a stopping rule; report the fit risk instead.
6. Hand off the top-2. Quote strength, approximate interval, comparison count,
   `probability_best`, the top-vs-runner-up probability, and the explicit
   `posterior_calibrated=False` caveat. If `insufficient_samples` is true, say so.

## Default judging criteria

- novelty
- feasibility
- falsifiability

## Guardrails

- Only compare hypothesis nodes against hypothesis nodes (the MCP enforces this and will raise).
- Keep reasons short and concrete; they are stored with the comparison and re-surfaced in the cockpit.
- Do **not** call either pause-suggestion tool from inside this skill. Pausing is
  a separate user or lifecycle-policy decision.
- If the cockpit is running, the BT update emits a `bt_rating_updated` event so the TUI's leaderboard updates without a manual refresh.
