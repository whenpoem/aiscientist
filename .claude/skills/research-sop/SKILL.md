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
5. **Preregister when the claim becomes confirmatory**: for exploratory prototypes, the engineer may run and pin results without a prereg as long as the output is labelled exploratory. Before promoting a result to a main confirmatory claim, run `$preregister` and lock metric, direction, threshold, alpha, and `mc_correction='bh'` into `ver_preregistrations`. The reviewer later refuses confirmatory manuscript claims whose matching prereg is not `met`.
6. **Implementation**: spawn the `engineer` subagent for the top hypothesis. Pass `prereg_id` when the work is confirmatory; otherwise tell the engineer the run is exploratory. Engineer must consult the `budgeter` agent before launching expensive work.
7. **Verification**: spawn the `verifier` subagent independently. Verifier calls `mcp__verify__seed_perturb` and resolves preregistrations only for confirmatory claims.
8. **Write-up**: only if the verifier passes AND the reviewer agent's `verdict` is `accept` for publication-critical claims. The reviewer must trace central result metrics back to a `pin_id`; confirmatory claims need `met` prereg and stable seed verdicts, while exploratory claims must be labelled as such. **If the manuscript contains theorem-shaped claims** (a `\begin{theorem}` block, a "we prove that" statement, or any quoted proposition node), the reviewer additionally runs the proof checklist from `$prove-sop` -- empty diagnostic manifest plus either a verified Lean attempt or an explicit `unverified` flag. Both checklists must pass for `verdict='accept'`.
9. **Realtime pruning (optional)**: at any point, run `mcp__memory__suggest_pause_low_strength(ucb_threshold=...)`. Default is dry-run; users with `RESEARCH_AGENT_AUTO_PRUNE=1` see actual pauses. Use `$replay` to second-guess a paused branch.

At every step, call `mcp__memory__propose_hypothesis` and `mcp__memory__attach_evidence` to keep the graph live. When the BT tournament hands off, cite the current `strength` and 95% interval (not just Elo) for each top candidate.
