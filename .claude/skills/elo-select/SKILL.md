---
name: elo-select
description: Rank competing hypotheses with pairwise Elo updates before choosing what to implement.
---

# Elo Select

Use this when multiple candidate hypotheses compete for the next experiment and you need a stable top-2 instead of picking the first option.

Workflow:
1. Gather the candidate hypothesis node IDs and texts.
2. For each comparison, call `mcp__memory__judge_hypotheses` to fetch the canonical comparison prompt.
3. Evaluate the prompt inline in the current Claude context. Do not spawn a separate subagent just to judge.
4. Call `mcp__memory__record_judgement` with the winner and a short reason.
5. Repeat until the ordering is clear. Prefer enough comparisons to separate the top-2 rather than exhausting all pairs blindly.
6. Return the top-2 hypotheses with their current Elo scores and the main reasons they won.

Default judging criteria:
- novelty
- feasibility
- falsifiability

Guardrails:
- Only compare hypothesis nodes against hypothesis nodes.
- Keep reasons concrete and short; they become part of the ledger.
- If two options are effectively tied, say so and note what experiment would break the tie.
