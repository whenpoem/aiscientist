---
name: research-sop
description: End-to-end research loop. Use at the start of any new research task — triggers literature review, hypothesis generation, experimentation, verification.
---

# Research SOP

When the user asks a research-shaped question ("investigate X", "does X affect Y", "compare A and B"):

1. **Memory lookup** — call `mcp__memory__match_signatures` with the task description. If prior failures exist, read them first.
2. **Literature gap** — call `mcp__memory__query_literature`. If fewer than 3 relevant papers exist, spawn the `librarian` subagent.
3. **Hypothesis generation** — spawn the `researcher` subagent with literature context. Ask for 3–5 hypotheses.
4. **Hypothesis selection** — present options to the user via cockpit, or inline if cockpit is not running. Pick one.
5. **Implementation** — spawn the `engineer` subagent.
6. **Verification** — spawn the `verifier` subagent independently.
7. **Write-up** — only if the verifier passes.

At every step, call `mcp__memory__propose_hypothesis` and `mcp__memory__attach_evidence` to keep the graph live.
