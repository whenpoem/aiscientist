# Roadmap

> 中文版本: [roadmap.zh-CN.md](roadmap.zh-CN.md)
> Mid-to-long term directions after v3.0. This is not a commitment list. It is a set of design judgments: given the existing architecture, what is most worth doing next, why, and how it might be implemented. Each direction includes an initial estimate of value and complexity.

## A note on current maturity

ClaudeScientist v3.0 has reached a usable level on the engineering of research workflows:

- **Mechanical layer is mature** — MCP tools, hook chain, SQLite state, TUI panes all work and are test-covered
- **Methodological layer is mature** — Bradley-Terry ranking, preregistration, provenance DAG, multiple-comparison correction are all in place
- **Ecosystem layer is shallow** — still a single-user, single-session, purely local tool; no cross-project collaboration, no cloud sync, no published comparison benchmark

The directions below cluster into three layers: **deepening existing capabilities** (1-4), **filling adjacent gaps** (5-7), and **moving toward an ecosystem** (8-10).

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

**Complexity**: Medium-high. Implementing the spending function math correctly is not hard but error-prone, and orthogonal composition with existing BH/Bonferroni correction needs design.

**Reference**: BH controls FDR across hypotheses; Alpha-Spending controls FWER across multiple checks within one hypothesis. The two are mathematically independent and stack cleanly.

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

**Today**: Design assumes single-user single-session. Two Claude Code sessions writing the same `state.db` simultaneously can under-correct BH because both see the same `open_count`.

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

## A few directions explicitly **not** on the roadmap

To avoid misinterpretation, here are directions I would not pursue:

- **Bring back the Web UI**. v0.2 had good reasons to delete it; do not retrace.
- **Replace SQLite with Postgres**. The single-file state boundary is one of the project's core advantages.
- **Support languages beyond English/Chinese**. No demand, and the i18n infrastructure can extend on demand.
- **Wire in Lean formal proofs**. Cost is high and value is narrow; if mathematical verification becomes a real need, try SymPy-based symbolic checks first as a lightweight substitute.

## Closing thought

The current core value of ClaudeScientist is "make AI-driven research workflows produce trustworthy results". Every future direction should center on that — directions that make numbers more trustworthy, processes more controllable, or memory more durable rank high; directions that drift away from this center (however technically interesting) deserve skepticism.
