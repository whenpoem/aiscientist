# MCP Tool Reference (v4.1.0a4)

> 中文版本: [tool-reference.zh-CN.md](tool-reference.zh-CN.md)
> Complete catalog of every MCP tool the project ships. Tools are grouped by server. Each entry lists the signature, what it does, what state it touches, and when you should call it. For the underlying contracts see [`architecture.md`](architecture.md); for end-to-end flows see [`workflows/`](workflows/).

## Quick index

- **memory MCP** — 23 tools for the hypothesis graph, BT ranking, calibration, replay, failure ledger, and literature
  - [Hypothesis graph](#hypothesis-graph) · [Failures](#failures) · [BT ranking](#bradley-terry-ranking) · [Calibration](#calibration) · [Replay](#replay) · [Snapshots](#snapshots) · [Literature](#literature)
- **verify MCP** — 13 tools for leakage, provenance, metrics, preregistration, held-out, and budget
  - [Leakage](#leakage) · [Provenance](#provenance) · [Pinned metrics](#pinned-metrics) · [Seed and fairness](#seed-and-fairness) · [Held-out](#held-out) · [Preregistration](#preregistration) · [Resource budget](#resource-budget)
- **prove MCP** *(v4.0)* — 18 tools for the proof trunk: corpus retrieval, NL workflow, Lean reinsurance
  - [Corpus + retrieval](#corpus-and-retrieval) · [Proof nodes](#proof-nodes) · [Segmentation + diagnosis](#segmentation-and-diagnosis) · [Correction](#correction) · [Lean reinsurance](#lean-reinsurance)
- **cockpit MCP** — 3 tools that let Claude push to the cockpit
  - [Cockpit bridge](#cockpit-bridge)

---

## Common patterns

Most tasks use a handful of tools in a predictable order. Here are the five patterns you'll reach for most often. Each one links to the detailed entries below.

### Starting a research task

1. `match_signatures` — check if you've hit a similar problem before
2. `query_literature` — see what's already published
3. `propose_hypothesis` (several times) — generate candidates
4. `judge_hypotheses` + `record_judgement` (in pairs) — run a tournament
5. `get_bt_leaderboard` — see which hypothesis is winning

### Running an experiment

1. `preregister` — lock the metric, direction, and threshold before you see results
2. `leakage_check` — scan the training script for data leaks
3. `budget_check` — make sure you have enough budget
4. Run the experiment (hooks handle provenance logging automatically)
5. `seed_perturb` — check reproducibility across seeds
6. `pin_metric` — record the headline number
7. `resolve_preregistration` — did you hit the target?

### Writing up results

1. `check_provenance` — for each claim, verify it has backing
2. `refresh_claim` — make sure the input files haven't changed
3. `find_contradictions` — check for conflicting claims in the graph
4. `baseline_fairness` — verify fair comparison with baselines

The `reviewer` agent calls these automatically and blocks any claim missing a pin, a stable seed verdict, a met preregistration, or fresh provenance.

### When something goes wrong

1. `match_signatures` — search for similar past failures before debugging
2. Fix the problem
3. `record_failure` — save the diagnosis so you (or Claude) never repeat it
4. `replay_counterfactual` — if you're second-guessing a pruned branch, explore "what if" without touching the live graph

### Proof workflow (v4.0)

1. `retrieve_skeletons` — find structurally similar proofs in the corpus
2. `propose_proposition` + `propose_proof_skeleton` — create the proof target and a candidate skeleton
3. `segment_proof` — break the draft into snippets
4. `diagnose_snippet` — check each snippet against the failure ledger
5. `apply_correction` — fix diagnosed issues
6. `triage_for_formalization` — if eligible, hand off to the prover agent for Lean verification

---

## memory MCP

Backed by the SQLite tables prefixed `mem_*` and `meta_*`. All tools below are exposed via the `mcp__memory__<name>` namespace inside Claude Code.

### Hypothesis graph

#### `propose_hypothesis(text, parent_id=None, rationale="")`
Append a hypothesis or question node to the research graph. If `parent_id` is provided, a `refines` edge is created. Initializes a `mem_bt_ratings` row with prior strength 0 and variance 1.0. Emits a `graph_delta` cockpit event.

**Returns**: `{"node_id": "hyp_..."}`

**When to use**: at the start of any new line of research, and whenever a sub-hypothesis spins off from an existing one.

#### `attach_evidence(node_id, evidence_text, polarity)`
Create an evidence node and link it to `node_id` with either a `supports` or a `refutes` edge.

**Returns**: `{"evidence_id": "ev_..."}`

**When to use**: every time an experiment produces a result that bears on an active hypothesis.

#### `mark_refuted(node_id, reason, evidence_ids=None)`
Flip the node's `state` to `refuted`. The provided evidence IDs are recorded as the rationale.

**Returns**: `{"refuted": "<id>", "reason": "..."}`

**When to use**: only when the evidence is conclusive enough to retire the hypothesis. Reversible only by a new hypothesis that supersedes it.

#### `get_active_frontier()`
Return up to 50 of the most recent hypothesis or question nodes whose `state='active'`.

**Returns**: `[{"node_id": ..., "kind": ..., "text": ..., "created_at": ...}, ...]`

**When to use**: every time a researcher subagent needs to see what's currently in flight before proposing more.

#### `get_ancestors(node_id)`
Walk the parent chain from `node_id` upward to the root.

**Returns**: list of node dicts in child-to-root order.

**When to use**: when you need to understand the full lineage of a hypothesis before judging it.

### Failures

#### `record_failure(trigger, symptom, root_cause="", resolution="")`
Insert a failure record into the FTS5-indexed `mem_failures` table. Computes a deterministic signature so duplicates increment `seen_count` instead of stacking.

**Returns**: `{"failure_id": <int>}`

**When to use**: every time a script fails, especially with a non-obvious root cause.

#### `match_signatures(situation, k=5)`
BM25-rank existing failures against `situation` and return the top `k`.

**Returns**: list of failure rows with `score`.

**When to use**: before writing a new training script, to catch "I've already tripped on this" cases.

### Bradley-Terry ranking

#### `judge_hypotheses(hypothesis_a_id, hypothesis_b_id, criteria=None)`
Fetch the canonical comparison prompt for a pair of hypotheses. Does not perform the comparison itself — Claude reads the returned prompt and decides.

**Returns**: `{"prompt": "...", "criteria": [...], "a": {...}, "b": {...}}`

**When to use**: as the first half of a BT comparison, paired with `record_judgement`.

#### `record_judgement(a_node_id, b_node_id, winner_node_id, reason="", k_factor=32.0, weight=1.0, source="llm_judge")`
Record a comparison and **dual-write**: it updates the legacy Elo on `mem_nodes.elo_score`, appends to `mem_judgements`, and applies an online BT update on `mem_bt_ratings`. Emits `bt_rating_updated`.

**Returns**: `{"judgement_id": <int>, "elo": {...}, "bt": {...}}`

**When to use**: whenever Claude has finished comparing two hypotheses (typically right after `judge_hypotheses`).

#### `update_bt_rating(winner_node_id, loser_node_id, source, weight=1.0, evidence_id=None, note="")`
A direct BT update path that does **not** dual-write to the Elo ledger. Accepts a wider set of sources than `record_judgement` (`metric_diff`, `user_intervention`, `reviewer_critic`).

**Returns**: `{"comparison_id": <int>, "bt": {...}}`

**When to use**: when the source of the comparison is something other than an LLM judge — e.g. an experimental result that directly favored one hypothesis.

#### `get_bt_leaderboard(top_k=20, include_paused=False)`
Return the top `top_k` hypotheses ranked by BT strength, with 95% LUCB intervals (`lcb`, `ucb`). Hypotheses with fewer than 3 comparisons are flagged `insufficient_samples=True`.

**Returns**: list of leaderboard rows.

**When to use**: at the end of a tournament round, before deciding which hypotheses to advance.

#### `suggest_pause_low_strength(ucb_threshold=-0.5, min_comparisons=6)`
Find every active hypothesis whose `n_comparisons >= min_comparisons` and `ucb < ucb_threshold`. By default emits only `branch_pause_suggested` events. With `RESEARCH_AGENT_AUTO_PRUNE=1` it additionally flips `mem_bt_ratings.status` to `paused` and emits `branch_paused`.

**Returns**: `{"candidates": [...], "auto_pruned": bool}`

**When to use**: periodically during a long research session, to identify branches that have lost the tournament.

#### `resume_branch(node_id, reason)`
Reverse a paused branch: status back to `active`, emits `branch_promoted`.

**Returns**: `{"resumed": "<id>", "reason": "..."}`

**When to use**: when new evidence revives a previously deprioritized direction.

#### `expected_information_gain(candidate_node_ids)`
For each candidate, compute the expected variance reduction from the next pairwise comparison against the current top-ranked hypothesis.

**Returns**: list of `{"node_id": ..., "eig": float, "current_var": float}`.

**When to use**: when the cost of a comparison is non-trivial and you want to pick the most informative pair to compare next.

### Calibration

#### `record_calibration(agent_name, predicted_p, observed_outcome, context="")`
Append one calibration sample for an agent. `predicted_p` should be the agent's stated probability that some outcome would occur; `observed_outcome` is whether it actually did (boolean).

**Returns**: `{"recorded": True, "bucket": <float>}`

**When to use**: every time an agent makes a confidence-bearing claim that can later be checked.

#### `calibration_report(agent_name=None)`
Aggregate calibration samples into reliability-diagram buckets (10 buckets at 0.05, 0.15, ..., 0.95). If `agent_name` is omitted, report on every agent.

**Returns**: `{"agents": {<name>: {"buckets": [...], "brier_score": <float>, ...}}}`

**When to use**: on a regular cadence (e.g. after every 50 judgements) to detect over-confidence drift.

### Replay

#### `replay_counterfactual(snapshot_id, counterfactual)`
Create a counterfactual branch from a saved snapshot. Writes only to `mem_replay_branches`; the main `mem_nodes` and `mem_bt_ratings` are untouched. Emits `replay_branch_created`.

**Returns**: `{"replay_id": "rep_...", "snapshot_id": "...", "counterfactual": "..."}`

**When to use**: when you want to ask "what if we had pursued the pruned branch instead" without risking the live state.

#### `list_replay_branches(limit=20)`
Return the most recent replay branches.

**Returns**: list of replay rows.

**When to use**: in an audit pass, when reviewing prior pruning decisions.

### Snapshots

#### `snapshot(label="")`
Capture the current graph + BT ratings into a frozen snapshot row.

**Returns**: `{"snapshot_id": "snap_...", "label": "...", "node_count": <int>}`

**When to use**: at meaningful checkpoints — end of a research session, before risky pruning, before publishing a result.

### Literature

#### `ingest_paper(paper_id, source, structured)`
Store a structured compression of a paper. The `structured` dict must contain `title`, `authors`, `year`, `venue`, `problem`, `method`, `claimed_results`, `assumptions`, `limitations`, `trust_level`, `raw_abstract`. Source must be one of `arxiv`, `openalex`, `manual`.

**Returns**: `{"ingested": "<paper_id>"}`

**When to use**: from inside the librarian subagent, after fetching the abstract via `arxiv` or `openalex`.

#### `query_literature(question, k=10)`
BM25-rank papers against `question`, weighted by `trust_level`.

**Returns**: list of paper dicts.

**When to use**: at the start of any literature-bearing research turn.

#### `find_baselines_for(method_description, k=5)`
Convenience wrapper around `query_literature` for finding methodologically similar papers.

**Returns**: same shape as `query_literature`.

**When to use**: when an engineer subagent is about to pick baselines for a comparison.

#### `find_contradictions()`
Surface pairs of nodes connected by a `contradicts` edge.

**Returns**: list of contradiction pairs.

**When to use**: in a reviewer audit, to make sure no shipped conclusion contradicts an earlier one.

---

## verify MCP

Backed by the `ver_*` and `res_*` tables. Exposed via `mcp__verify__<name>`.

### Leakage

#### `leakage_check(script_path=None, script_text=None)`
AST-scan a Python script for known leakage patterns: `fit()` on concatenated train+test, reads from held-out paths, common label-leak idioms.

**Returns**: `{"clean": bool, "findings": [{"rule": ..., "line": ..., "message": ...}]}`

**When to use**: before running any training script, especially one that touches splits.

### Provenance

#### `record_provenance(claim, value, session_id, source_command="", input_files=None, parent_prov_ids=None)`
Append a provenance row for a numeric claim. When `input_files` is provided, each path is sha256-hashed and the fingerprint is stored in `ver_provenance_dag`, enabling later re-validation by `refresh_claim`.

**Returns**: `{"recorded": True, "provenance_id": <int>, "dag": {...}}`

**When to use**: every time a script reports a numeric result that you might cite later.

#### `check_provenance(claim)`
Look up a claim and return its pin (if any), seed verdict, and source command.

**Returns**: `{"status": "found"|"missing", "evidence": {...}}`

**When to use**: by the writeup workflow before any numeric claim makes it into a manuscript.

#### `refresh_claim(claim)`
Re-hash every input file in the claim's provenance DAG and compare to stored hashes. Emits `prov_dag_stale` for any drift.

**Returns**: `{"status": "fresh"|"stale", "drifted_files": [...]}`

**When to use**: at writeup time, and after any change to upstream data files.

### Pinned metrics

#### `pin_metric(claim, value, session_id, source_command="", note="")`
Pin a central metric so the writeup workflow knows which numbers matter. Creates one provenance row and one `ver_metric_pins` row, linking them. Emits `claim_pinned`.

**Returns**: `{"pinned": True, "pin_id": <int>, "provenance_id": <int>}`

**When to use**: for each headline number a research artifact will report.

### Seed and fairness

#### `seed_perturb(script_path, seed_arg="--seed", seeds=None, metric_pattern=..., metric_pin_id=None, timeout_sec=600)`
Run `script_path` once per seed (defaults to `[0, 1, 2]`). Extract the metric from each stdout, compute mean and standard deviation, classify the verdict as `stable` or `unstable` (threshold: std < 0.01). When `metric_pin_id` is given, the seed run is linked to that pin so writeup checks can find it.

**Returns**: `{"ok": True, "values": [...], "mean": ..., "std": ..., "verdict": "stable"|"unstable"}`

**When to use**: for every metric pin that will end up in a writeup.

#### `baseline_fairness(proposed_log, baseline_log, threshold_ratio=3.0)`
Parse two run logs to extract `epochs`, `lr_trials`, and `param_count`. Flag the comparison as `unfair` if any axis has a ratio above `threshold_ratio`.

**Returns**: `{"verdict": "fair"|"unfair", "ratios": {...}, "unfair_axes": {...}}`

**When to use**: whenever a paper's results compare a proposed method to a baseline.

### Held-out

#### `query_heldout(dataset, model_path, batch_size=1)`
The only legitimate access path to held-out data. Reserves budget *before* execution, verifies the manifest sha256, runs the model script with a temporary access grant, records the query, and returns **only** the parsed metric (not stdout/stderr).

**Returns**: `{"ok": True, "metric": <float>, "remaining_budget": <int>}`

**When to use**: only after the proposed approach has passed all internal validation; typically once per project lifetime per dataset.

### Preregistration

#### `preregister(hypothesis_id, metric, direction, threshold, mc_correction="bh", alpha=0.05, seeds=None, note="")`
Lock the falsification target for a hypothesis **before any experiment runs**. `direction` must be one of `higher_better` or `lower_better`. `mc_correction` must be one of `bh`, `bonferroni`, `none`; current `bh` and `bonferroni` modes are v3.0-compatible aliases for the same Bonferroni-style calculation. Emits `prereg_locked`.

**Returns**: `{"prereg_id": "preg_...", "alpha_adjusted": <float>}`

**When to use**: as the gate between the BT tournament and the engineer subagent. No experiment should run without one.

#### `resolve_preregistration(prereg_id, observed_value, observed_p_value=None, note="")`
Compare `observed_value` against the locked threshold and direction. If `observed_p_value` is given, apply the multiple-comparison correction across all currently-open prereg rows. Emits `prereg_resolved`.

**Returns**: `{"status": "met"|"unmet", "adjusted_p_value": ..., ...}`

**When to use**: after the experiment finishes and the metric has been pinned.

#### `list_preregistrations(hypothesis_id=None, status=None)`
Filter active and historical preregistrations.

**Returns**: list of prereg rows.

**When to use**: by the reviewer agent to understand the open universe of tests before resolving.

### Resource budget

#### `budget_check(scope, resource, window)`
Read-only inspection of a `(scope, resource, window)` ledger row.

- `scope`: typically `session`, `per_hypothesis`, or `global`
- `resource`: one of `wallclock_sec`, `llm_tokens`, `heldout_queries`, `disk_mb`
- `window`: time window key

**Returns**: `{"limit": ..., "used": ..., "remaining": ...}`

**When to use**: before launching any expensive operation.

#### `budget_consume(scope, resource, window, amount)`
Atomically decrement the budget. Overflow returns `{"ok": False, "error": "budget_exceeded"}` and emits `budget_exceeded`.

**Returns**: `{"ok": True, "remaining": ...}` on success.

**When to use**: by the budgeter agent or directly by the engineer, immediately before consuming resources.

---

## prove MCP *(v4.0)*

Backed by the `prv_*` tables and the cross-domain `mem_failures.domain` column. Exposed via `mcp__prove__<name>`. The proof trunk's primary path is StatProver-style (corpus retrieval -> draft -> segment -> diagnose -> correct); Lean is reinsurance on top. See [ADR 0008](adr/0008-two-trunk-domain-architecture.md) and [architecture.md §13](architecture.md#13-core-vs-domain-trunks-v40).

### Corpus and retrieval

#### `ingest_proof_corpus(source, problems)`
Bulk-ingest a list of proof problems into `prv_corpus_problems` + `prv_corpus_keywords`. Each problem must include `problem_id`, `statement`, and at least one of `lexical_keywords` / `semantic_keywords`. Optional fields: `reference_proof`, `domain_tags`. Re-ingesting an existing `problem_id` replaces it (idempotent upsert). Keywords are vectorised through the active embedding backend (`RESEARCH_AGENT_EMBED_BACKEND`: `mock` | `local` | `openai`; Claude settings default to `mock` so the MCP starts without optional embedding packages); each keyword row records `embed_backend` + `embed_dim` so retrieval can refuse cross-backend mixing.

**Returns**: `{"ingested": int, "replaced": int, "backend": str, "dim": int}`

**When to use**: at project start to seed the corpus from StatEval / arXiv / hand-curated examples.

#### `list_corpus(source=None, limit=20)`
Browse the corpus with aggregated keyword counts.

**Returns**: list of `{problem_id, source, statement, reference_proof, domain_tags, n_lexical, n_semantic, ingested_at}`.

#### `retrieve_skeletons(proposition_text, lexical_keywords, semantic_keywords, k=5)`
Bidirectional max-matching retrieval (architecture.md §13 formula). The agent extracts keyword sets from the proposition via an LLM call before invoking; this tool does pure vector math.

**Returns**: list of `{problem_id, source, statement, reference_proof, domain_tags, lexical_score, semantic_score, similarity}`. Sorted by `similarity` descending.

**When to use**: at the top of `prove-sop` to find structurally similar lemmas before drafting.

### Proof nodes

#### `propose_proposition(text, parent_id=None)`
Create a `proposition` node (the proof-trunk peer of a hypothesis). Attach to a question node so propositions and hypotheses share one tree.

**Returns**: `{"node_id": "prop_..."}`

#### `propose_proof_skeleton(proposition_id, text, note="")`
Create a candidate proof skeleton under a proposition. Seeds a `mem_bt_ratings` row for the proof-skeleton tournament.

**Returns**: `{"node_id": "psk_..."}`

#### `register_proof_draft(skeleton_id, draft_text, note="")`
Persist a generated LaTeX draft as a child `proof_skeleton` revision. The parent chain encodes revision history.

**Returns**: `{"node_id": "psk_...", "parent_skeleton_id": "..."}`

#### `list_proof_drafts(proposition_id, limit=20)`
List `proof_skeleton` descendants under a proposition, ordered deepest-first and newest-first. Used by the reviewer proof checklist to find the latest draft before calling `list_diagnostic_manifests`.

### Segmentation and diagnosis

#### `segment_proof(draft_id, snippets)`
Persist agent-segmented snippets and open a fresh diagnostic manifest in `status='open'`.

**Returns**: `{"manifest_id": int, "snippet_ids": [...]}`

#### `list_proof_snippets(draft_id)`
Browse snippets in insertion order.

#### `diagnose_snippet(snippet_id, k=5)`
Read-only. Searches `mem_failures` with `domain='proof'` for the top-k historical proof errors resembling this snippet; returns the candidates plus a structured prompt for the agent's judgment.

**Returns**: `{snippet_id, snippet_text, candidates: [...], prompt: str}`

#### `register_diagnosis(manifest_id, snippet_id, is_flawed, description, matched_failure_ids=[])`
Append one diagnosis entry to a manifest. Allowed only while the manifest is `status='open'`.

#### `finalize_manifest(manifest_id)`
Close diagnosis: `empty` if no flawed entries, else stays `open` for correction.

#### `list_diagnostic_manifests(draft_id=None, status=None)`
Browse manifests. Used by the reviewer's proof checklist (P5).

### Correction

#### `compose_correction_prompt(draft_id, manifest_id)`
Read-only. Assembles the original draft + per-flaw descriptions into a single global-fix prompt for the agent.

#### `apply_correction(draft_id, manifest_id, corrected_text, note="")`
Persist the corrected draft as a new `proof_skeleton` revision and mark the manifest `status='applied'`.

**Returns**: `{new_draft_id, old_draft_id, manifest_id, manifest_status}`

### Lean reinsurance

#### `triage_for_formalization(proposition_id)`
Decide whether to hand a proposition to the prover agent. Returns `{eligible, reasons, estimated_difficulty, whitelist_hits, blacklist_hits, length}`. Pure read; the agent inspects `eligible` before spawning prover.

#### `record_lean_attempt(proposition_id, status, lean_source="", stderr="", duration_sec=None, triage=None)`
Persist a Lean attempt to `prv_lean_attempts`. **No automatic cross-trunk side effects** -- the prover agent's prompt explicitly calls `attach_evidence` on success and `record_failure(domain='proof')` on failure so each side effect is auditable in the cockpit.

#### `list_lean_attempts(proposition_id=None, status=None)`
Browse Lean attempts.

---

## cockpit MCP

A small stdio bridge that lets Claude push to the cockpit. Exposed via `mcp__cockpit__<name>`.

### Cockpit bridge

#### `push_graph_delta(node_id, kind, text)`
Insert a synthetic `graph_delta` event so the cockpit lights up even when the graph change came from outside `memory_mcp`.

**Returns**: `{"ok": True}`

**When to use**: rarely — the memory MCP usually emits this automatically. Reserved for special integration scenarios.

#### `queue_intervention(kind, target=None, payload="")`
Programmatic equivalent of the user pressing a key in the cockpit. Useful for scripted interventions.

**Returns**: `{"ok": True, "intervention_id": <int>}`

**When to use**: in test fixtures or batch processing.

#### `record_note(text)`
Append a free-form note to the cockpit event stream.

**Returns**: `{"ok": True}`

**When to use**: when Claude wants to leave a marker in the event log for later review.

---

## External MCPs

These are installed as third-party packages; we do not own their schemas. They are listed here for completeness.

| Server | Source | Use |
|---|---|---|
| `arxiv` | `arxiv-mcp-server` | Search and fetch arXiv papers |
| `openalex` | `openalex-research-mcp` (npx) | Search and fetch OpenAlex works |

---

## Conventions

- All tools return JSON-serializable dicts.
- Error responses follow the shape `{"ok": False, "error": "<reason>"}` where applicable.
- Tools that emit cockpit events do so inside the same SQL transaction as the underlying state change.
- Tool signatures rarely change; new capabilities are added as new tools rather than as new parameters on existing tools.

If you find a discrepancy between this document and the source code, the source code is authoritative — please open an issue so this document can be updated.
