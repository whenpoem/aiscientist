---
name: replay
description: Audit a past pruning or approval decision by creating a counterfactual branch from a saved snapshot without mutating the live graph. Use when the user asks what would have happened under another decision, disputes a paused branch, or wants to inspect an earlier checkpoint.
---

# Replay

Replay is an inspection over frozen state. It does not execute new experiments
and must not modify live graph nodes, ratings, judgments, or preregistrations.

## Workflow

1. If the user did not provide a snapshot id, call
   `mcp__memory__list_snapshots(limit=20)`. Show label, timestamp, and counts;
   do not create a new snapshot merely to replay the past.
2. Phrase exactly one counterfactual in a falsifiable sentence, such as
   `Approve hyp_07 instead of pausing it`.
3. Call `mcp__memory__replay_counterfactual(snapshot_id, counterfactual)` and
   retain the returned `branch_id`.
4. Inspect only the recorded snapshot and branch metadata. Do not call model
   scripts, `seed_perturb`, or the sequestered-data query tool.
5. If the analysis suggests a live action, report it as a recommendation. The
   user may later call `resume_branch`; replay itself never flips status.

## Output shape

Return:

```text
snapshot_id: <snap_...>
branch_id: <replay_...>
counterfactual: <one sentence>
live_graph_mutated: false
evidence: <recorded facts used>
finding: <what changes under the counterfactual>
recommendation: <none or explicit user action>
limitations: <what replay cannot establish without a new experiment>
```

For several what-ifs, create one replay branch per counterfactual and keep each
output independent. Use `mcp__memory__list_replay_branches(limit=20)` to audit
existing branches before adding duplicates.

## Completion criteria

Replay is complete when the source snapshot and new branch are identifiable,
the live graph is unchanged, every finding cites recorded snapshot evidence,
and any proposed live change is clearly left for separate user approval.
