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
4. Pull the leaderboard via `mcp__memory__get_bt_leaderboard(top_k=10)`. Look at `strength`, `lcb`, `ucb`, `n_comparisons`, and `insufficient_samples`.
5. Decide whether to run another comparison. Interval separation is supporting
   evidence, not proof of a clear winner. Stop when every serious candidate
   has at least 3 relevant comparisons, the ranking is stable to reasonable
   judging criteria, the budget is exhausted, or the user chooses.
6. Hand off the top-2. Quote strength, approximate interval, comparison count,
   and `interval_calibrated=False`. If `insufficient_samples` is true, say so.

## Default judging criteria

- novelty
- feasibility
- falsifiability

## Guardrails

- Only compare hypothesis nodes against hypothesis nodes (the MCP enforces this and will raise).
- Keep reasons short and concrete; they are stored with the comparison and re-surfaced in the cockpit.
- Do **not** call `mcp__memory__suggest_pause_low_strength` from inside this skill. That is a separate decision the user (or P3 hooks) takes.
- If the cockpit is running, the BT update emits a `bt_rating_updated` event so the TUI's leaderboard updates without a manual refresh.
