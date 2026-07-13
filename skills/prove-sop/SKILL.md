---
name: prove-sop
description: Build and audit a statistical or mathematical proof from proposition capture through skeleton selection, diagnosis, correction, optional empirical checking, and optional Lean reinsurance. Use when the user asks to prove or rigorously derive a proposition, a graph proposition lacks a verified proof, or a reviewer requires a theorem-side gate.
---

# Prove SOP

Treat this skill as a router. Read [references/proof-loop.md](references/proof-loop.md)
before starting a new proof or resuming an incomplete proof loop.

## Route the request

1. Identify the proposition, assumptions, requested rigor, and desired output.
2. Look up related proof failures with
   `mcp__memory__match_signatures(..., domain="proof")` before drafting.
3. Register the proposition if it is not already in the shared graph.
4. Follow the proof loop reference through skeleton selection, draft diagnosis,
   correction, and review.
5. Add an empirical companion only when a constant or premise needs data.
6. Use Lean only as optional reinsurance for a small, closed, formalization-ready
   claim; a missing Lean tool or failed attempt does not invalidate a sound
   natural-language proof.

## Required boundaries

- Compare only candidates of the same graph kind.
- Treat BT intervals as uncalibrated approximate posterior summaries. Never call
  their separation a significance test or use it as the sole stopping rule.
- `diagnose_snippet` is read-only; persist each judgment explicitly with
  `register_diagnosis`.
- Corrected drafts need a new segmentation and diagnostic manifest. Preserve old
  manifests as audit history.
- Check wall-clock budget before a Lean attempt expected to take at least five
  minutes, and record actual use afterward.
- If the optional `prover` or `budgeter` agent is unavailable, perform the same
  checks inline and report that the specialized agent surface was absent.

## Completion

Finish only when the proposition and final draft are identifiable, the latest
diagnostic manifest is empty or every remaining limitation is explicit, the
manuscript states Lean verification status honestly, and any empirical companion
has passed its own preregistration and provenance gates.
