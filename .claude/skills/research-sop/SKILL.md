---
name: research-sop
description: End-to-end research loop. Use at the start of any new research task; triggers literature review, hypothesis generation, Elo selection, experimentation, and verification.
---

# Research SOP

When the user asks a research-shaped question ("investigate X", "does X affect Y", "compare A and B"):

1. **Memory lookup**: call `mcp__memory__match_signatures` with the task description. If prior failures exist, read them first.
2. **Literature gap**: call `mcp__memory__query_literature`. If fewer than 3 relevant papers exist, spawn the `librarian` subagent.
3. **Hypothesis generation**: spawn the `researcher` subagent with literature context. Ask for 3-5 hypotheses.
4. **Hypothesis selection**: if you have 3 or more candidates, run `$bt-tournament` (V3.0 successor of `elo-select`). Use `mcp__memory__judge_hypotheses` and `mcp__memory__record_judgement` to rank them; the call dual-writes to the BT comparison ledger. Inspect `mcp__memory__get_bt_leaderboard` and keep the top 2 only when their 95% intervals separate. Otherwise run more comparisons.
5. **Preregister**: BEFORE the engineer touches code, run `$preregister` for each hypothesis you plan to test. Lock metric, direction, threshold, alpha, and `mc_correction='bh'` into `ver_preregistrations`. The reviewer agent later refuses any manuscript whose claims have no `met` prereg.
6. **Implementation**: spawn the `engineer` subagent for the top hypothesis. Pass the `prereg_id`. Engineer must consult the `budgeter` agent before launching expensive work.
7. **Verification**: spawn the `verifier` subagent independently. Verifier calls `mcp__verify__seed_perturb` and `mcp__verify__resolve_preregistration`.
8. **Write-up**: only if the verifier passes AND the reviewer agent's `verdict` is `accept`. The reviewer must trace every numeric claim back to a `pin_id` whose prereg is `met` and whose seed verdict is `stable`. **If the manuscript contains theorem-shaped claims** (a `\begin{theorem}` block, a "we prove that" statement, or any quoted proposition node), the reviewer additionally runs the proof checklist from `$prove-sop` -- empty diagnostic manifest plus either a verified Lean attempt or an explicit `unverified` flag. Both checklists must pass for `verdict='accept'`.
9. **Realtime pruning (optional)**: at any point, run `mcp__memory__suggest_pause_low_strength(ucb_threshold=...)`. Default is dry-run; users with `RESEARCH_AGENT_AUTO_PRUNE=1` see actual pauses. Use `$replay` to second-guess a paused branch.

At every step, call `mcp__memory__propose_hypothesis` and `mcp__memory__attach_evidence` to keep the graph live. When the BT tournament hands off, cite the current `strength` and 95% interval (not just Elo) for each top candidate.
