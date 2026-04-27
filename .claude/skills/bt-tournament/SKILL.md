---
name: bt-tournament
description: Rank competing hypotheses with online Bradley-Terry updates and LUCB intervals. Replaces elo-select. Use whenever there are 3 or more candidate hypotheses competing for the next experiment, or when the user wants to understand which branch is currently leading.
---

# BT Tournament

This skill is the V3.0 successor to `elo-select`. It runs an online Bradley-Terry tournament instead of one-shot Elo updates and exposes 95% confidence intervals so "low-confidence ties" stay visible.

## When to invoke

- Researcher subagent has just emitted >= 3 hypothesis nodes in one turn.
- The user explicitly typed `/bt-tournament`.
- The cockpit shows two candidates whose 95% intervals overlap and the user asks which to push first.

## Workflow

1. Gather the candidate hypothesis node ids and texts from `mcp__memory__get_active_frontier`.
2. For each pair you intend to compare, call `mcp__memory__judge_hypotheses` to fetch the canonical comparison prompt. Evaluate inline (do not spawn a sub-agent just to judge).
3. Decide a winner. Call `mcp__memory__record_judgement(a, b, winner, reason)`. Internally this dual-writes to the legacy Elo ledger AND the BT comparison ledger; you do not need to call `update_bt_rating` separately.
4. Pull the leaderboard via `mcp__memory__get_bt_leaderboard(top_k=10)`. Look at `strength`, `lcb`, `ucb`, `n_comparisons`, and `insufficient_samples`.
5. Decide whether to run another comparison. Stop when:
   - The top-2 LCB / UCB intervals no longer overlap (clear winner), OR
   - At least 3 comparisons have been logged for every candidate, OR
   - The user already approved a target.
6. Hand off the top-2 to the engineer. Quote each hypothesis's BT strength and the 95% interval. If `insufficient_samples` is true for any winner, say so explicitly.

## Default judging criteria (mirrors the legacy elo-select)

- novelty
- feasibility
- falsifiability

## Guardrails

- Only compare hypothesis nodes against hypothesis nodes (the MCP enforces this and will raise).
- Keep reasons short and concrete; they are appended to `mem_judgements.reason` and re-surfaced in the cockpit.
- Do **not** call `mcp__memory__suggest_pause_low_strength` from inside this skill. That is a separate decision the user (or P3 hooks) takes.
- If the cockpit is running, the BT update emits a `bt_rating_updated` event so the TUI's leaderboard updates without a manual refresh.

## Deprecation note

`elo-select` is kept as a backwards-compatibility shim and routes here internally. All new SOPs (research-sop) reference this skill directly.
