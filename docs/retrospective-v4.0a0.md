# Retrospective — v4.0.0a0

> 中文版本: [retrospective-v4.0a0.zh-CN.md](retrospective-v4.0a0.zh-CN.md)
>
> Written after Plan v2 closed out the v4.0 alpha. Captures three things:
> what shipped, the system-auto-decision audit findings (with which were
> fixed in this pass and which were filed for later), and concrete
> follow-up suggestions ordered by impact-vs-effort.

## What landed

Plan v1 (P0–P5, ~10 weeks) and Plan v2 (this pass) together delivered:

**Architecture**
- Two-trunk architecture (ADR 0008): existing empirical trunk + new
  proof trunk, sharing one core (graph, failures, BT, calibration,
  cockpit) with exactly four cooperation interfaces.
- Tools/Skills/Hooks layering doctrine (ADR 0007) prevents the proof
  trunk from collapsing into a hardcoded pipeline.

**Code surface**
- New MCP server: `prove_mcp` (18 tools across corpus, retrieval,
  proof nodes, segmentation, diagnosis, correction, Lean reinsurance).
- Embedding adapter with three backends (mock / local /
  sentence-transformers / openai). Mock for tests, local default for
  live use, openai opt-in.
- Memory MCP extensions: `mem_failures.domain` (cross-domain failure
  ledger), `mem_nodes.kind` widened to include proof kinds, BT
  comparison primitive accepts both `hypothesis` and `proof_skeleton`.
- Lean MCP wrapper (`scripts/lean_mcp_or_noop.py`) auto-dispatches:
  toolchain present → real `lean-lsp-mcp`; absent → clean exit-0 noop.
  No more manual `_lean → lean` rename.

**Cold-start data**
- `data/proof_corpus_seed.jsonl` — 85 hand-curated statistical proof
  problems across 8 clusters. Verified end-to-end retrieval: a
  Markov-style query top-1 hits `markov_inequality` at sim=0.889
  with the live `local` embedding backend.
- `data/proof_failure_seed.jsonl` — 84 paraphrased proof failure
  modes covering 9 categories.
- `scripts/seed_proof_corpus.py` and `scripts/seed_proof_failures.py`
  with idempotent ingest semantics.

**Reviewer + cockpit**
- Reviewer agent gained the proof checklist (`numeric_claims` +
  `theorem_claims` JSON output, parallel hard rules per claim).
- Cockpit i18n labels for all proof-trunk events; tree pane shows
  proof kinds with distinct prefixes/colors.

**Ops integration**
- Snapshot covers proof subtree (proposition frontier + recent drafts
  + manifests + lean attempts + corpus count). v3.0-only DBs degrade
  to empty proof sections via `sqlite3.OperationalError` wraps.
- `stop_flush` digest reports proof manifest / Lean attempt /
  wallclock totals per turn.
- Prover agent prompt requires `budgeter` round-trip before any
  Lean attempt ≥ 5 minutes.

**Test count**: 239 green (203 pre-Plan-v2 baseline + 36 new across
seed scripts, snapshot proof coverage, stop_flush proof coverage,
triage regression, BT pause-suggestion coverage, Lean wrapper).

## System-auto-decision audit

Plan v2 deliberately included an audit of every place the system
makes an automatic decision (whitelist/blacklist, threshold cutoff,
substring match, status enum check, defensive read). Below are the
findings with disposition.

### Fixed in this pass

| ID | Severity | Location | Description |
|---|---|---|---|
| **A** | medium | `prove_mcp/tools/lean_bridge.py` | Triage whitelist too narrow — rejected ~10 of 85 seed corpus problems (Borel-Cantelli, Hoeffding, Rao-Blackwell, sub-Gaussian, KL, Pinsker, Glivenko-Cantelli, Wald/score test, Lehmann-Scheffé). Whitelist expanded from 30 to ~90 keywords across all 8 corpus clusters. |
| **B** | low | same | Blacklist over-aggressive: `lebesgue integral`, `ergodic`, `measure-preserving` are well-covered in mathlib but were rejected. Removed. Kept only the genuinely thin areas (Itô, SDEs, Banach/Hilbert/Sobolev abstraction, infinite-dimensional). |
| **C** | low | same | Substring matching without word boundaries — `ols` matched `controls`, `tools`. Added `_WORD_BOUNDARY_REQUIRED = {ols, mle, rao, ump, blue, ito}` for tokens that need `\b…\b` regex anchoring. |
| **D** | cosmetic | same | Rejected propositions got `difficulty='high'` (misleading; "high" implies "eligible but hard"). Now returns `'n/a'`. Added schema_version 4 migration to widen the `prv_lean_attempts.triage_difficulty` CHECK constraint. |
| **M** | medium | `memory_mcp/tools/bt.py` | `suggest_pause_low_strength` hardcoded `WHERE n.kind = 'hypothesis'`. Proof tournament was unprunable. Now defaults to walking both `BT_RANKABLE_KINDS`; accepts `kind=` filter for targeted use. |

### Filed for v4.x (not fixed in this pass)

| ID | Severity | Location | Why deferred |
|---|---|---|---|
| **E** | medium | `.claude/hooks/leakage_guard.py:171` | Markdown verification gates by directory name (`reports`, `writeup`). Manuscripts in `paper/`, `submission/`, `manuscript/`, `final/` etc. bypass the numeric-claim provenance check. **Fix**: switch to content-based detection (look for `\\begin{theorem}`, `\\section`, "we prove that", numeric tokens density) plus the directory hint as one signal. Out of scope for the "no new logic" pass. |
| **F** | medium | `runtime.py:204` (METRIC_RE) | Label list (`acc, f1, auc, loss, precision, recall, mse, rmse, mae, bleu, rouge, score, metric`) is biased toward classic ML benchmarks. Misses stat-specific metrics: `p-value`, `coverage`, `power`, `effect_size`, `cohen_d`, `chi2`, `t-stat`, `iou`, `ndcg`, `map`, `top-1/5`. **Fix**: extend the label union and unit-test each new label against a fixture markdown. |
| **G** | low-medium | runtime.py:204 (METRIC_RE) | Value pattern `[-+]?\d+(?:\.\d+)?%?` rejects scientific notation. `p < 1.2e-3` doesn't trigger the markdown guard. **Fix**: extend pattern to `(?:[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?%?)`. |
| **J** | low-medium | `.claude/hooks/destructive_bash_guard.py:11` | Pattern `\brm\s+-rf\b` doesn't catch separated flags (`rm -r -f`, `rm --recursive --force`). |
| **K** | medium | same file | No pattern for shell redirect zero-out (`> important.txt`), `rmdir /s /q`, `git branch -D`, `git stash drop`. |
| **L** | low | `bt.py:327` (`update_bt_rating`) | Doesn't dual-write to `mem_nodes.elo_score`; only `record_judgement` does. Display-only impact (BT strength is the source of truth). **Fix**: either remove the dual-write from `record_judgement` or add it here for consistency. |
| **N** | low (now), medium (at scale) | `prove_mcp/tools/retrieval.py` | No SQL `LIKE` prefilter — dense rerank over the entire corpus per query. Fine ≤2k items, slows at 5k+. **Fix**: add `LIKE` prefilter when `len(corpus) > 2000`. |
| **O** | medium | `verify_mcp/tools/verification.py:71` | `seed_perturb` `stability_tol=0.01` is absolute; meaningless for metrics outside [0,1]. **Fix**: `stability_tol` becomes `(absolute, relative)` tuple, take the max. |
| **P** | low | same | 1-seed run defaults `std_value=0.0` → trivially "stable" with zero evidence. **Fix**: emit verdict `"insufficient_seeds"` when `len(seeds) < 2`. |
| **Q** | cosmetic | `prove_mcp/tools/diagnosis.py` | Manifest `status='open'` is overloaded: pre-finalize (still being diagnosed) and post-finalize-with-flaws (waiting for correction) look identical. **Fix**: split into `open` / `awaiting_correction`, or add `finalized_at` timestamp semantics. |

### Known design choices (not bugs)

These look like bugs but are actually intentional:

- **Reviewer is a soft gate**: only `leakage_guard` is a hook (hard rule). The reviewer subagent has to be explicitly spawned. This is documented in ADR 0007 (Tools/Skills/Hooks layering). If the user skips spawning reviewer, theorem claims pass un-checked.
- **`destructive_bash_guard` is a speed bump**: not exhaustive. Documented as such in `.claude/hooks/README.md`. The convention is `# CONFIRM_DESTRUCTIVE` for everything not explicitly listed.
- **Default sources are fixed enums**: `ingest_proof_corpus` only accepts `{stateval, manual, arxiv}`. Adding a fourth requires both the `VALID_SOURCES` set AND the schema CHECK constraint, with a migration. This is friction by design — telemetry consistency over user freedom.
- **Auto-prune is dry-run by default**: `RESEARCH_AGENT_AUTO_PRUNE=1` is required to actually `paused`. Conservative default; users opt in.
- **Triage is a heuristic, not an oracle**: keyword-based eligibility is intentionally crude (ADR 0007). The agent can override (with user approval per `prover.md`). Better long-term path is a quick `lean leansearch` probe before triage commits to a verdict.

## v4.0a0 → v4.0a1 follow-up suggestions

Ordered by impact ÷ effort. Items in this list are **strictly improvements
to existing functionality**; no new features.

### Tier 1 (do soon — high impact, low effort)

1. **Bug F + G**: extend `METRIC_RE` to cover stat-specific labels and
   scientific notation. ~10 line change in `runtime.py` plus 2-3 unit
   tests in `tests/test_runtime.py`. **Effort**: 1 hour.
   **Impact**: closes the biggest gap in the leakage hook's coverage of
   non-ML manuscripts.

2. **Bug E**: add content-based detection to `_should_verify_markdown`.
   Match any markdown file containing `\\begin{theorem}`, `\\section`,
   or N-or-more numeric tokens, regardless of directory. **Effort**: 2
   hours. **Impact**: leakage hook stops being directory-name dependent.

3. **Bug J + K**: extend `destructive_bash_guard` patterns. **Effort**:
   30 min. **Impact**: marginal but tightens the safety speed bump.

### Tier 2 (do when relevant)

4. **Bug O + P**: `seed_perturb` scale-aware tolerance and 1-seed
   handling. **Effort**: 2 hours. **Impact**: only matters once a real
   research project exercises seed_perturb on non-accuracy metrics.

5. **Bug Q**: split manifest `open` status. **Effort**: 4 hours
   (touches schema + diagnosis.py + correction.py + tests + docs).
   **Impact**: clarity for audit trails. Currently a cosmetic issue.

6. **Bug L**: decide on the `update_bt_rating` ↔ `mem_nodes.elo_score`
   dual-write asymmetry. **Effort**: 30 min. **Impact**: tiny; only
   affects display.

### Tier 3 (do at scale)

7. **Bug N**: SQL `LIKE` prefilter in `retrieve_skeletons`. Don't bother
   until the corpus crosses ~2000 problems. The seed corpus is 85, so
   we have a 20× headroom before this matters.

### Lean reinsurance follow-ups (separate track)

8. **Spike templates need mathlib-version tracking**. The 5 spike
   `.lean` files use `Mathlib.Algebra.BigOperators.Basic` which moved
   in mathlib v4.13+. Need to either pin a specific mathlib commit or
   teach the prover agent to discover the new path automatically.
   **Effort**: 1-2 days for the discovery agent path; 30 min for the
   pinning path. The pinning path is fragile (mathlib moves quickly);
   the discovery path is the right answer long-term.

9. **`scripts/run_spikes.py` records all-failed when imports stale**.
   Currently this would pollute `prv_lean_attempts` with 5 failed rows
   on every run until the imports are fixed. Consider adding
   `--dry-run` mode or auto-skip on first import error. **Effort**: 1
   hour.

## Reflection

### What worked

- **The four-interface design held up**. Through Plan v1 + v2 + this
  audit, the cooperation surface between the empirical and proof
  trunks stayed at exactly four interfaces (one tree, one failure
  ledger, one BT leaderboard, one reviewer with two checklists). No
  hidden coupling sneaked in.

- **`mem_failures.domain` was the right primitive**. Adding a single
  string column and defaulting it to `'empirical'` was enough to make
  the cross-domain failure ledger work. No new tables, no migration
  pain. This is exactly the "extend, don't replace" pattern ADR 0007
  prescribes.

- **The mock embedding backend let tests stay deterministic at zero
  cost**. 239 tests run in ~70 seconds because no test ever loads
  sentence-transformers. The live backend was only validated end-to-end
  by manual run.

- **ADR 0007's "atomic verbs" rule prevented pipeline-ization**. Every
  new prove_mcp tool is a single verb. The `prove-sop` skill is
  suggestion-mode markdown, not enforced sequencing. The temptation
  to write `run_full_proof_workflow()` was real and was correctly
  resisted.

### What didn't

- **Whitelist-based heuristics ossify**. The triage whitelist hardcoded
  in v0.1 became progressively wronger as the corpus grew. Discovered
  in this audit that ~12% of seed problems were rejected. Whitelists
  for taste-of-the-week mathlib coverage will keep drifting; replacing
  with a quick `lean leansearch` probe is the right architectural fix
  but is a v4.x item.

- **Schema CHECK constraints are heavy to migrate**. Bug D's "rename
  `'high'` → `'n/a'` for rejected" required a full SQLite table rebuild
  because CHECK can't be altered. This is a known SQLite pain. For
  future enums prefer a separate "valid values" table or a runtime-only
  check rather than baking into schema.

- **Lean spike templates were optimistic about mathlib stability**.
  Authored against `Mathlib.Algebra.BigOperators.Basic` which moved in
  v4.13. The "starting points for prover loop" framing covers this, but
  it'd be cleaner to pin a known-good mathlib commit in the lakefile.

- **Cold-start data scope discovery requires hands-on use**. We
  shipped 85 + 84 rows based on coverage breadth (8 clusters × ~10
  items), but the right question is "do retrievals for typical user
  queries return useful candidates?". Validating that requires running
  real research projects, which Plan v2 did not do. This is the
  legitimate next-iteration loop: ship → use → ingest user-discovered
  failures → grow corpus.

## Closing

v4.0.0a0 is a coherent alpha. The architecture (two trunks, four
interfaces) is right. The code is consistent (atomic verbs, reviewer
contract, snapshot scope, budgeter integration). The cold-start data
is small but real (live retrieval working at sim=0.889 for canonical
queries). The audit found 12 things worth fixing; 5 fixed now, 7 filed
for v4.x with explicit severity and effort estimates.

The remaining work is **iterative refinement, not redesign**.

---

*Retrospective version: 1.0 · 2026-05-07 · tag: `v4.0.0a0`*
