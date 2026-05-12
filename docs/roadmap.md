# Roadmap

> 中文版本: [roadmap.zh-CN.md](roadmap.zh-CN.md)
> Mid-to-long term directions after v3.0. This is not a commitment list. It is a set of design judgments: given the existing architecture, what is most worth doing next, why, and how it might be implemented. Each direction includes an initial estimate of value and complexity.

## A note on current maturity

ClaudeScientist v3.0 has reached a usable level on the engineering of research workflows:

- **Mechanical layer is mature** — MCP tools, hook chain, SQLite state, TUI panes all work and are test-covered
- **Methodological layer is mature** — Bradley-Terry ranking, preregistration, provenance DAG, multiple-comparison correction are all in place
- **Ecosystem layer is shallow** — still a single-user, single-session, purely local tool; no cross-project collaboration, no cloud sync, no published comparison benchmark

The directions below cluster into three layers: **deepening existing capabilities** (1-4), **filling adjacent gaps** (5-7), and **moving toward an ecosystem** (8-10). Direction 11 is the v4.0 commitment that supersedes the prior "no Lean" stance and adds a parallel proof trunk; it is documented separately in [ADR 0008](adr/0008-two-trunk-domain-architecture.md) and the v4.0 phasing plan.

---

## I. Deepening existing capabilities

### Direction 1: Promote BT ranking from passive sorting to active experimental design

**Today**: `expected_information_gain` already computes the expected variance reduction from comparing each candidate against the leader, but invocation is manual and the strategy is greedy.

**Proposal**: Replace the greedy choice with **Thompson Sampling**. To pick the next pair to compare, sample from each hypothesis's posterior `N(strength, strength_var)` and select the two with the highest sampled values.

**Value**: High. Thompson Sampling has an O(√(K ln K · T)) regret bound under the multi-armed bandit framing, balancing exploration (high-variance dark horses) and exploitation (already-confirmed leaders) automatically. This turns the BT tournament from "sort after the fact" into "actively design the next experiment", saving a meaningful number of comparisons.

**Complexity**: Low. A new `thompson_select_pair` tool in `memory_mcp/impl.py`, core implementation just a few lines of `random.gauss`.

**Constraint**: Decide when to trigger it — possibly as an opt-in mode of the `bt-tournament` skill, or as a parallel option next to `expected_information_gain`.

---

### Direction 2: Close the loop on meta-calibration

**Today**: The `meta_calibration` table records per-agent calibration data and can output reliability diagrams and Brier scores, but the data is display-only — it never feeds back into decisions.

**Proposal**: Wire calibration into the `weight` argument of `update_bt_rating`. When a comparison's source is `llm_judge`, look up the judge's historical calibration error in the matching confidence bucket and discount the weight:

```
weight *= 1 - calibration_error_at_bucket(judge_name, predicted_p)
```

Well-calibrated judges keep full weight; poorly-calibrated ones get auto-downweighted.

**Value**: Medium-high. Implements adaptive trust management for the system's own judgements. Multi-model collaboration scenarios (Sonnet for researcher, Opus for reviewer) get differentiated handling for free.

**Complexity**: Medium. Decisions needed: decay window for calibration error (most recent N or full history), minimum sample threshold (so a brand-new agent isn't penalized immediately), and how to expose the dynamic weights in the cockpit.

---

### Direction 3: Lineage-aware "genetic distance" propagation

**Today**: `suggest_pause_low_strength` evaluates each hypothesis's UCB independently. But the hypothesis graph is a tree — children share premises with their parents. When a parent is refuted, its descendants' priors should drop too.

**Proposal**: When a hypothesis `H_parent`'s BT strength drops sharply, propagate the drop to descendants with depth-decay:

```python
for child in descendants(H_parent):
    depth = path_length(H_parent, child)
    decay = 0.5 ** depth
    child.strength -= delta_parent * decay
    child.strength_var += abs(delta_parent * decay) * 0.1
```

**Value**: Medium-high. Saves significant manual intervention when the research tree is deep (5-6 levels). On shallow trees, mostly inert.

**Complexity**: Medium. The decay coefficient (0.5) is intuition, not theory; it needs validation. Visualization of "propagation events" in the cockpit needs care — users should not see a wave of weakening hypotheses without knowing why.

**Risk**: If the parent was refuted in error, propagation amplifies the mistake. `mark_refuted` must remain reversible, or a "propagation confidence" concept needs introducing.

---

### Direction 4: Extend the provenance chain to experiment scripts

**Today**: `ver_provenance_dag` only hashes input data files. If the experiment script itself is edited and re-run, `refresh_claim` cannot detect it.

**Proposal**: Multi-level script tracking:

- **Level 1**: Script file SHA-256 (any change triggers)
- **Level 2**: AST hash, ignoring comments and whitespace (only logical changes trigger)
- **Level 3**: Critical-path hash — only `fit`/`predict`/`forward` and similar call sites (only core-logic changes trigger)

Different levels emit different severity events: Level 2 → "suggest re-run", Level 3 → "force re-run".

**Value**: High. This is a known hole — the docs claim a closed provenance loop, but in reality only the data half is closed.

**Complexity**: Medium. Python's `ast` module is directly usable; a canonical AST serialization is needed for stable hashes.

---

## II. Filling adjacent gaps

### Direction 5: Sequential analysis for preregistration

**Today**: Preregistration uses fixed-sample-size design — lock the threshold, run all seeds, judge once.

**Proposal**: Introduce **Alpha-Spending functions** (O'Brien-Fleming style) for early stopping:

- At preregistration time, lock a `spending_function='obrien_fleming'`
- After each completed seed, call `interim_check(prereg_id, current_values)`
- The function allocates the current checkpoint's alpha portion per the spending schedule and computes a Z statistic
- Extreme positive effect → early efficacy stop
- Extreme negative effect → early futility stop

**Value**: High. In deep learning experiments where a single training run takes hours or days, early termination saves significant compute budget.

**Complexity**: Medium-high. Implementing the spending function math correctly is not hard but error-prone, and orthogonal composition with the existing preregistration correction needs design. True rank-based BH remains a separate behavior change.

**Reference**: True rank-based BH controls FDR across hypotheses; Alpha-Spending controls FWER across multiple checks within one hypothesis. The two are mathematically independent and stack cleanly.

---

### Direction 6: Semantic upgrade of failure signatures

**Today**: `match_signatures` uses SQLite FTS5's BM25 text matching. "CUDA out of memory" and "GPU memory exhausted" match poorly under BM25 despite being the same problem.

**Proposal**: Layer semantic matching on top of FTS5:

- Use a small local model (e.g. `all-MiniLM-L6-v2`, ~80MB) to vectorize each failure
- Store in a new `embedding BLOB` column on `mem_failures`
- Hybrid ranking in `match_signatures`: `final = 0.6 * bm25_norm + 0.4 * cosine`
- Periodic HDBSCAN clustering to auto-group similar failures

**Value**: Medium-high. The failure ledger is "the part of the system that pays the most compound interest" — improving its recall translates directly to debugging time saved.

**Complexity**: Medium. Adds a local embedding model dependency; the 0.6/0.4 weights need tuning.

**Constraint**: Vectorization must be async — `record_failure` cannot block on model loading.

---

### Direction 7: A "research rhythm" pane in the cockpit

**Today**: The Event Stream is a linear time series. Users can see "what happened" but cannot see at a glance "where the research is in its arc".

**Proposal**: Add a Rhythm Pane using Textual's built-in Sparkline widget to show several time series:

- **Hypothesis production rate** (new hypotheses per hour) — exploration intensity
- **Pruning rate** (refuted/paused per hour) — convergence trend
- **Total BT uncertainty** (sum of `strength_var` across active hypotheses) — global confidence
- **Budget consumption curves** (wallclock / token / sequestered queries as progress bars)

Together they form an "EKG" of the research: at a glance you can tell whether you're in divergent exploration (high production, low pruning, high uncertainty) or convergent confirmation (low production, high pruning, rapidly dropping uncertainty).

**Value**: Medium. Clear value for long-session users.

**Complexity**: Low. Textual's `Sparkline` is plug-and-play; the data aggregates from existing `cockpit_events`.

---

## III. Moving toward an ecosystem

### Direction 8: Optimistic concurrency control for multi-session use

**Today**: Design assumes single-user single-session. Two Claude Code sessions writing the same `state.db` simultaneously can under-correct preregistration thresholds because both see the same `open_count`.

**Proposal**: Add a `version INTEGER DEFAULT 0` column to critical tables (`ver_preregistrations`, `mem_bt_ratings`, `res_budget_ledger`). Convert all writes to compare-and-swap:

```sql
UPDATE ver_preregistrations
SET status = 'met', version = version + 1
WHERE prereg_id = ? AND version = ?;
-- if affected_rows == 0, conflict detected; reread and retry
```

**Value**: Medium. No real multi-user scenario today, but this is the prerequisite for any "scale to team collaboration".

**Complexity**: Medium-high. CAS itself is straightforward, but auditing every existing write site and designing concurrency tests takes effort.

---

### Direction 9: Auto-rebuild the hypothesis graph from Git history

**Today**: Cold-start cost is high — a project that's been worked on for six months ends up with an empty hypothesis graph after migrating to ClaudeScientist.

**Proposal**: A new `archaeologist` skill or CLI tool that scans Git history and semi-automatically rebuilds a retrospective hypothesis graph:

- Created/modified experiment scripts per commit → candidate hypothesis nodes
- Numeric claims in commit messages (same regex as `provenance_log.py`) → candidate evidence
- Reverted or abandoned branches → candidate refuted hypotheses
- Branch-name keywords → candidate question nodes

After extraction, the user manually confirms or rejects each candidate before it lands in the main graph.

**Value**: High. Determines whether the project can be used in real-world research scenarios with existing history, not just from a fresh start.

**Complexity**: High. Semantic extraction from Git history needs some NLP work, and the UX needs polish (importing six months of history at once is overwhelming — phased import or label-based filtering needed).

---

### Direction 10: Publish a comparison benchmark

**Today**: The project has all the pieces needed to compare against EvoScientist, AI Scientist v2, and similar systems, but no public benchmark.

**Proposal**: Pick one or two standard tasks (idea generation benchmark, experiment reproducibility benchmark) and run a head-to-head against EvoScientist under matched conditions, measuring:

- **Idea novelty** — coverage gap against retrieved literature
- **Idea feasibility** — scored by the reviewer agent
- **Reproducibility** — multi-seed verdict stability rate
- **Memory leverage** — debugging time saved by failure-ledger hits

**Value**: High. External users need an objective answer to "why use this instead of others".

**Complexity**: High. Two or more weeks of standalone work, plus reproducing EvoScientist's runtime.

**Prerequisite**: Direction 9 is likely the import vehicle for the comparison subjects.

---

## IV. Domain expansion (v4.0)

### Direction 11: Proof trunk — NL primary path with Lean reinsurance

**Today**: ClaudeScientist is a single-trunk system focused on ML empirical reproducibility. The `prover` agent has been a stub since v0.1 and Lean integration was previously listed under "do not pursue" (see superseded note at the bottom of this document).

**Proposal**: Adopt a two-trunk architecture (formalised in [ADR 0008](adr/0008-two-trunk-domain-architecture.md)). The existing v3.0 surface becomes the **empirical trunk**; a new **proof trunk** is added in `src/prove_mcp/`. The proof trunk's primary path is StatProver-style: corpus retrieval (bidirectional max-matching, dual-keyword embeddings), draft generation, snippet segmentation, diagnosis against `mem_failures(domain='proof')`, delayed global correction. A Lean formalisation layer is bolted on as **reinsurance**, not as the main path: only propositions that pass `triage_for_formalization` are sent to the prover agent (now backed by `lean-lsp-mcp`); successful Lean verifications attach as strong evidence, failures feed back into the cross-domain failure ledger.

The two trunks share four cooperation interfaces (one tree, one failure ledger, one BT leaderboard, one reviewer with two checklists) and exactly four — see architecture.md §13.

**Value**: Very high. Statistical research projects mix theoretical and empirical work; bridging them under one toolchain is a real product-level differentiator. None of the current single-trunk competitors (StatProver, EvoScientist, AI Scientist v2) offer the cross-domain failure matching or the dual-checklist reviewer.

**Complexity**: High. ~10 weeks across six phases (P0 docs → P1 core domain-agnostic → P2 retrieval → P3 NL workflow → P4 Lean reinsurance → P5 cooperation surface). A new MCP server (`prove_mcp`) is added — the v3.0 default of "no new MCP server" is intentionally relaxed for this domain expansion.

**Constraints**:
- Layering doctrine ([ADR 0007](adr/0007-tools-skills-hooks-layering.md)) is binding from day one. New proof tools must remain atomic verbs; the StatProver pipeline lives in `prove-sop` skill markdown, not in code.
- We will not match StatProver's 40k-corpus / 80k-error-repo scale. Our wedge is workflow integration, not retrieval quality.
- Lean reinsurance is opt-in per proposition; we never gate the workflow on Lean success.

**Status**: alpha shipped in v4.0.0a0 (P0–P5 + Plan v2 cold-start data + Lean activation prep).

**Deferred to v4.x**:
- Theorem-claim hook gate (the `\begin{theorem}` regex in
  `leakage_guard.py`).
- `CHANGELOG.md` capturing the v3.0 → v4.0 jump.
- FTS5 on `prv_corpus_problems` for >5k corpora (current scale doesn't
  need it).
- Domain-aware `meta_calibration` so per-agent reliability tracks
  empirical vs proof verdicts separately.

---

## Suggested execution order

If you start today, I would suggest this order:

1. **Direction 1 (Thompson Sampling)** — high value, low cost, validatable in hours
2. **Direction 4 (script provenance)** — closes a known provenance hole
3. **Direction 7 (rhythm pane)** — short and sweet, UX win
4. **Direction 6 (semantic failure matching)** — medium investment, long compound returns
5. **Direction 2 (meta-calibration loop)** — wait until multi-model usage matures
6. **Direction 5 (sequential analysis)** — math needs care but the payoff is large
7. **Direction 3 (lineage propagation)** — most economical once the research tree has grown
8. **Direction 8 (concurrency control)** — wait for actual multi-user demand
9. **Direction 9 (Git archaeology)** — extend cold-start once the core stabilizes
10. **Direction 10 (comparison benchmark)** — only after the system has driven a few real research projects

**Direction 11 (Proof trunk)** has shipped as v4.0.0a0; remaining items are listed under that direction's "Deferred to v4.x" block above.

## What v4.2 actually delivered

v4.2.0 shipped across four alphas with a focused theme: information
architecture refit, multi-provider retrieval, reports infrastructure,
cold-start polish. Items now closed:

- TUI tab grouping + Collapsible detail sections + pane-scoped keys
  (a1). The TUI no longer absorbs new content shape via density tricks.
- Reports as files (a2 + [ADR 0009](adr/0009-reports-as-files-monitoring-as-tui.md)).
  Five report kinds (closure / draft / diagnostic / portfolio / cascade)
  × two formats (markdown / html). Indexed by `cockpit_reports`,
  surfaced in the new Reports tab, opened in the user's default app.
- Reviewer agent optional `mcp__verify__export_report` integration —
  attach a closure report path in `notes` without changing the hard
  rules.
- Multi-provider embeddings ([ADR 0010](adr/0010-multi-provider-embeddings.md)).
  `OpenAIEmbedder` accepts any compatible `base_url`. DashScope, Jina,
  Voyage, GLM tested.
- Default local model upgraded to `Qwen/Qwen3-Embedding-0.6B` for
  multilingual retrieval. `(backend, model, dim)` triple per corpus
  row; `scripts/reindex_proof_corpus.py` re-encodes after a switch.
- Cold-start Welcome screen (a3) with i18n + persisted dismiss flag.
- Wizard provider preset menu + first-task walkthrough prompt.

Retrospective: [`retrospective-v4.2.md`](retrospective-v4.2.md).

## A few directions explicitly **not** on the roadmap

To avoid misinterpretation, here are directions I would not pursue:

- **Bring back the Web UI**. v0.2 had good reasons to delete it; do
  not retrace. ADR 0009 reaffirms the no-web-UI stance and adds the
  "reports as files" channel as the right way to surface dense
  content without reopening the question.
- **`claudescientist start` launcher** (any variant). Permanently
  removed during v4.2 planning. Two-terminal manual startup remains
  the contract; tmux users get `tmux split-window` on their own.
- **Replace SQLite with Postgres**. The single-file state boundary is
  one of the project's core advantages.
- **Support languages beyond English/Chinese**. No demand, and the
  i18n infrastructure can extend on demand.
- ~~**Wire in Lean formal proofs**.~~ **Superseded by Direction 11
  (v4.0)**: the proof trunk integrates Lean as a reinsurance layer
  with NL as the primary path. The original objection (high cost,
  narrow value) was correct in a single-trunk world; the two-trunk
  architecture changes the calculus by sharing the existing
  infrastructure (BT, calibration, provenance, replay, cockpit,
  failure ledger) with the proof workflow at near-zero marginal
  cost. See [ADR 0008](adr/0008-two-trunk-domain-architecture.md).

## Closing thought

The current core value of ClaudeScientist is "make AI-driven research workflows produce trustworthy results". Every future direction should center on that — directions that make numbers more trustworthy, processes more controllable, or memory more durable rank high; directions that drift away from this center (however technically interesting) deserve skepticism.
