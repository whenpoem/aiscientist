# ADR 0006: Preregistration correction aliases as the writeup gate

- **Status**: Accepted (v3.0)
- **Date**: 2026-04

## Context

In v0.2 the verification stack already gave us pinned metrics, seed
perturbation verdicts, leakage checks, and provenance records. But the
"writeup" step - producing a markdown report with numeric claims - had
no enforcement of the most common research-integrity failure modes:

1. **p-hacking**: choosing the threshold and direction *after* seeing
   results.
2. **Multiple comparisons without correction**: running many tests, then
   reporting whichever one happened to clear `alpha=0.05`.
3. **Stale provenance**: citing a number whose underlying input data has
   changed since the experiment ran.

Asking the user to remember these rules would defeat the purpose. The
hooks already block leakage and destructive commands by construction; we
needed the same mechanical guarantee for trustworthy numeric claims.

## Decision

Introduce a preregistration mechanism with the following rules:

- `preregister(hypothesis_id, metric_name, direction, threshold,
  mc_correction='bh', alpha=0.05, ...)` writes a row to
  `ver_preregistrations` with `status='open'`. This must happen **before**
  the experiment runs.
- `resolve_preregistration(prereg_id, observed_value, observed_p_value)`
  freezes the verdict (`met` or `missed`). Multiple-comparison correction
  applies based on the count of *currently open* prereg rows:
  - `bh`: accepted for v3.0 compatibility, but currently an alias for the
    Bonferroni-style calculation below. It is **not** rank-based
    Benjamini-Hochberg.
  - `bonferroni`: alpha / max(1, open_count); raw p multiplied by
    open_count.
  - `none`: no adjustment (must be explicitly chosen).
- True Benjamini-Hochberg would require rank-based thresholds over the
  correction family (`alpha * k / m`) and monotonic adjusted p-values. That
  would change verdict behavior, so it is deferred to a separate behavioral
  fix rather than folded into a maintainability refactor.
- The reviewer agent refuses to draft any markdown that mentions a
  numeric claim unless that claim has all four of: a `ver_metric_pins`
  row, a `ver_seed_runs.verdict='stable'` row, a
  `ver_preregistrations.status='met'` row, and a fresh
  `ver_provenance_dag` (no drift detected by `refresh_claim`).

`refresh_claim` re-hashes input files for a claim's provenance DAG and
emits `prov_dag_stale` events; stale provenance blocks publication-critical
claims. Missing DAG rows are audit warnings unless the claim has no other
trace.

## Consequences

### Positive

- p-hacking is blocked by construction: thresholds are locked before
  experiments. Changing a locked prereg requires opening a new one,
  which the audit trail makes visible.
- Multiple-comparison correction tightens automatically as more preregs
  open simultaneously. The current calculation is conservative and
  Bonferroni-style; it does not yet provide rank-based FDR control.
- The reviewer's verdict ("accept" / "refuse with blockers") is
  programmatically derived; the user cannot accidentally ship a number
  that does not trace back.
- `refresh_claim` catches the "I edited the data file but forgot to
  rerun" failure mode that no amount of human review reliably catches.

### Negative

- The workflow is more rigid. A user who wants to do exploratory
  analysis must explicitly mark it as such (no preregistration) and
  accept that the reviewer will reject it for publication.
- Locking too many preregs at once forces a strict alpha that may make
  every individual test impossible to clear. This is correct statistical
  behavior but may surprise users; documented in
  [`docs/workflows/writing-a-paper.md`](../workflows/writing-a-paper.md).
- The mechanism only constrains the writeup workflow. Numbers can still
  appear in commit messages, scratch files, or chat output without
  passing the relevant anchors. We accept this; the gate is at
  publication-critical claims, not at every utterance.

### Alternatives considered

- **Preregistration without correction** - lost because the
  multiple-comparison failure mode is the more pernicious one.
- **Implement true Benjamini-Hochberg immediately** - deferred because it
  would change statistical verdicts and needs dedicated tests plus a clear
  definition of the correction family.
- **Expose Bonferroni only** - lost because existing v3.0 callers may already
  pass `mc_correction='bh'`; keeping it as a compatibility alias avoids a
  tool-contract break.
- **Trust-the-user, no enforcement** - lost; this is exactly what every
  other AI scientist system does and exactly the bar we are trying to
  raise.

## References

- Originating discussion: [`docs/archive/plan-v3.0.md`](../archive/plan-v3.0.md)
  section 7.
- Implementation: [`src/verify_mcp/tools/prereg.py`](../../src/verify_mcp/tools/prereg.py),
  [`src/verify_mcp/tools/provenance.py`](../../src/verify_mcp/tools/provenance.py).
- Workflow guide: [`docs/workflows/writing-a-paper.md`](../workflows/writing-a-paper.md).
- Cross-component contract: [`docs/architecture.md`](../architecture.md) section 7.
