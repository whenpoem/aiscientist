---
name: replay
description: Run a counterfactual ("what if we had approved hyp_07 instead of pruning it") against a saved snapshot without mutating the live graph. Use when the user wants to second-guess a paused branch or audit a past pruning decision.
---

# Replay (Counterfactual)

This skill spawns a parallel "what-if" timeline rooted at an existing `mem_snapshots` row. It does **not** modify `mem_nodes`, `mem_bt_ratings`, or `mem_judgements`. The branch is recorded in `mem_replay_branches` and surfaced in the cockpit's `Replay` tab.

## When to invoke

- The user types `/replay`.
- The cockpit shows a `branch_paused` event the user disagrees with — replay lets them simulate the alternative path before deciding whether to call `mcp__memory__resume_branch`.
- Post-mortem after a missed preregistration: replay against the snapshot from before the prereg lock to inspect what the alternative hypothesis would have looked like.

## Workflow

1. Pick the snapshot. If the user did not name one, list recent snapshots via the cockpit (snapshots are also visible from `mcp__memory__snapshot` outputs in earlier turns).
2. Phrase the counterfactual in one sentence. Examples:
   - `"Approve hyp_07 instead of pruning it"`
   - `"Tighten preregistration alpha to 0.01 instead of 0.05"`
   - `"Use seed budget 10 instead of 3 for hyp_03"`
3. Call `mcp__memory__replay_counterfactual(snapshot_id, counterfactual)`. Capture the returned `branch_id`.
4. Run any inspection / hypothetical analysis you need INSIDE the response (no Bash, no file writes). All conclusions must reference the `branch_id` so the cockpit can group them.
5. If the replay produces an actionable suggestion, write it as a `cockpit_interventions` row (kind=`note`) so the user can promote it later via `mcp__memory__resume_branch`. Do not flip statuses yourself.

## Guardrails

- **Read-only effect on the live graph.** The MCP tool is implemented to refuse writes to `mem_nodes` from this path; you should refuse too.
- One replay = one counterfactual. If the user wants to compare three what-ifs, create three branches with separate `branch_id`s.
- The replay does not run new code. It does not call `seed_perturb`, `query_heldout`, or any model script. It is purely an inspection over already-recorded state.
- Replay branches accumulate; the cockpit lists the latest 20 newest-first. Older branches stay queryable via `mcp__memory__list_replay_branches(limit=N)`.
