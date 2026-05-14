# Architecture and Design Contracts

> 中文版本: [architecture.zh-CN.md](architecture.zh-CN.md)

This document describes the contracts between modules — the rules that keep the system working. Don't change any of these without a migration and matching tests.

## How to use this document

**Part I** covers the contracts you need to understand before touching any code: what the modules are, how they share state, what's protected, and what's deliberately left flexible. Read it first.

**Part II** is reference material: the BT math, event schemas, hook wiring, and the v4.0 trunk layout. Look things up here when you need specifics.

---

## Part I — Contracts

### 1. Module map

ClaudeScientist is composed of four runtime layers and one shared state file.

| Layer | Package | Process model | Talks to |
|---|---|---|---|
| **Runtime core** | `claudescientist` | Library (no daemon) | All other layers |
| **Memory MCP** | `memory_mcp` | One stdio subprocess per Claude Code session | SQLite, Claude over stdio |
| **Verify MCP** | `verify_mcp` | One stdio subprocess per Claude Code session | SQLite, Claude over stdio |
| **Cockpit** | `cockpit` | TUI process (Terminal B) **+** stdio MCP bridge | SQLite |
| **Hooks** | `.claude/hooks/*.py` | Short-lived processes spawned by Claude Code at lifecycle events | SQLite |

The five layers never call each other directly. They all talk through the SQLite file at `.research-agent/state.db`.

### 2. The state file

`.research-agent/state.db` is the **single local state boundary** for memory, verification, the cockpit, and hooks. Two rules:

1. **Each component owns its own tables.** Prefix conventions: `mem_*`, `ver_*`, `res_*`, `cockpit_*`, plus the shared `ra_migrations` and `meta_*` tables.
2. **Cross-component signals go through `cockpit_events`.** Only reach into another module's tables for read-only inspection in tests.

Long-running code and MCP tools must open the database with `connect_sqlite()` — it sets up WAL mode, foreign keys, row factories, and a 5-second busy timeout. Short-lived hooks use `connect_existing_sqlite()` instead so a missing or malformed first-run DB fails open without creating a new state file. Don't open raw `sqlite3` connections in runtime code.

### 3. Held-out data protection

Held-out data (typically test sets) is doubly protected. Both layers must hold for the contract to be intact.

- **Direct file access is blocked by hooks.** The PreToolUse hook `leakage_guard.py` denies any `Read`/`Write`/`Edit`/`Bash` whose path resolves into a registered held-out directory. The block is unconditional unless the env var `RESEARCH_AGENT_VERIFY=1` is set, which only `verify_mcp` is allowed to set.
- **`query_heldout` is the only intended access path.** It reserves budget *before* running the model script, records a query row, and **does not return raw stdout or stderr** because those streams may contain leaked labels or rows. Failed executions still consume reserved budget, because the script was already granted access.

If a hook or tool anywhere needs to bypass these protections, the bypass must come with a written justification and an additional unit test.

### 4. Agent tool contracts

Agent prompts and tool whitelists are part of the architecture, not just configuration. Two rules:

1. **When an MCP tool becomes part of the research workflow, update the relevant agent file.** Add a smoke assertion that the tool name appears in the agent prompt, so prompt and reality can't drift apart silently.
2. **The verifier role is the integration point for verification tools.** It must have access to leakage detection, provenance, seed stability, baseline fairness, and held-out budget tools. Other roles get a strict subset.

The current role assignments live in `.claude/agents/`. Treat them as part of the source of truth.

### 5. What this contract leaves open

Some things are deliberately not fixed here, because they are expected to evolve:

- **The exact set of MCP tools.** New tools land in the existing memory and verify servers without requiring a new MCP server, per the v3.0 plan.
- **Cockpit pane layout.** The grid, modals, and keybindings can change as long as the data contract holds.
- **Subagent prompts.** They can be revised freely, as long as the tool whitelist matches the role's contract (§4).
- **External literature MCPs.** `arxiv-mcp-server` and `openalex-research-mcp` are installed as-is; we own only the `ingest_paper` compression layer in `memory_mcp`.

### 6. How to break a contract

If a future change requires breaking one of the contracts above:

1. Open an issue describing what breaks and why.
2. Write the migration that moves the database forward.
3. Update this document **before** writing the code.
4. Add or update the test that pins the new contract.

Silent contract changes are the highest-severity bug class in this project.

---

## Part II — Reference

### 7. Shared runtime internals

The `claudescientist.runtime` module owns the four pieces of cross-module infrastructure that every layer depends on:

- **Path resolution.** `state_db_path()`, `heldout_root()`, and friends are the only legitimate way to locate shared resources. Feature packages must not duplicate path resolution; in particular, held-out roots must come from `runtime.heldout_root()` or from a registered `ver_heldout_budgets.heldout_path` row.
- **SQLite connection setup.** `connect_sqlite()` enables WAL mode, foreign keys, row factories, and a 5-second busy timeout. `connect_existing_sqlite()` is the hook-safe variant: it returns `None` instead of creating the DB when state is missing or malformed.
- **Schema migration bookkeeping.** The `ra_migrations` table records, per component, the schema version, schema hash, apply status, and any failure text. Structural upgrades that cannot be expressed by `CREATE TABLE IF NOT EXISTS` must use explicit compatibility helpers and ship with tests.
- **Cockpit event insertion.** `emit_cockpit_event()` is the canonical way to push something to the cockpit. Producers should call it inside the same transaction as the underlying state change.

### 8. Event kinds and cockpit labels

The cockpit reacts to these event kinds. Producers must include either `node_id`, `hypothesis_id`, or both in the JSON payload when relevant:

| Kind | Producer | When |
|---|---|---|
| `graph_delta` | memory MCP | New node or edge created |
| `failure_added` | memory MCP | New failure record inserted |
| `bt_rating_updated` | memory MCP | Bradley-Terry comparison applied |
| `branch_pause_suggested` | memory MCP | Low-strength dry-run flag |
| `branch_paused` / `branch_promoted` | memory MCP | Real status flip (auto-prune mode only) |
| `prereg_locked` / `prereg_resolved` | verify MCP | Preregistration lifecycle |
| `prov_dag_stale` | verify MCP | `refresh_claim` detected drift |
| `seed_run_recorded` | verify MCP | A `seed_perturb` invocation completed |
| `heldout_query_recorded` | verify MCP | A held-out query consumed budget |
| `budget_exceeded` | verify MCP | A `budget_consume` call hit the cap |
| `replay_branch_created` | memory MCP | A counterfactual branch was created |
| `intervention` | cockpit | A user wrote to `cockpit_interventions` |
| `note` | cockpit | A free-form `:note` entry |
| `turn_end` | hook | The `Stop` hook fired |

The cockpit can always be manually refreshed, but normal workflows should not depend on manual refresh to discover important state changes.

**User-facing labels**: All cockpit-visible labels must go through `cockpit.i18n` so English and Chinese modes stay aligned. Hard-coded strings inside widgets are a regression.

### 9. The Bradley-Terry layer (v3.0)

The hypothesis-ranking system that replaced the v0.2 Elo layer.

- **`mem_bt_ratings` is the canonical hypothesis ranking.** Prefer `strength`, `strength_var`, and `n_comparisons`.
- **`mem_nodes.elo_score` is kept only for backwards compatibility.** Existing v0.2 readers (and the tree pane's trailing display) can still read it, but no new feature should depend on it.
- **`record_judgement` is the only tool that dual-writes** to both the legacy `mem_judgements` ledger and the new `mem_bt_comparisons` ledger. `update_bt_rating` writes only to the new ledger but accepts a broader source set: `llm_judge`, `metric_diff`, `user_intervention`, `reviewer_critic`.
- **`suggest_pause_low_strength` is dry-run by default.** The env var `RESEARCH_AGENT_AUTO_PRUNE=1` is the only way to flip `mem_bt_ratings.status` to `paused`. `resume_branch` is the only allowed reversal path.
- **`replay_counterfactual` must not mutate `mem_nodes` or `mem_bt_ratings`.** It only writes a row to `mem_replay_branches`.

#### The math, briefly

For a single comparison with `winner=i, loser=j`:

```
diff   = clip(theta_i - theta_j, [-30, 30])
p      = sigmoid(diff)
fisher = max(1e-6, p * (1-p)) * weight
delta  = lr * weight * (1 - p)            # lr = 0.5
theta_i := clip(theta_i + delta, [-12, 12])
theta_j := clip(theta_j - delta, [-12, 12])
var_i := 1 / (1/var_i + fisher)
var_j := 1 / (1/var_j + fisher)
```

Confidence intervals on the leaderboard are `lcb = strength - 1.96 * sqrt(var)` and `ucb = strength + 1.96 * sqrt(var)`. The initial `strength_var = 1.0` plus the strength clip act as a Beta(1,1) shrinkage prior, bounding deterministic blowups when one node always wins.

### 10. Preregistration and the provenance DAG (v3.0)

These two mechanisms together enforce trustworthy numeric claims.

- **Publication-critical numeric claims should trace** to pinned provenance, stable seed evidence, and, when the claim is confirmatory, a `ver_preregistrations.prereg_id` whose `status='met'`. Exploratory results must be labelled as exploratory instead of being silently promoted to main claims.
- **`ver_provenance_dag.input_hashes` records the sha256 of every cited input file at record time.** `refresh_claim` re-hashes and emits `prov_dag_stale` events on drift. Stale provenance blocks publication-critical claims; missing DAG rows are reported as unchecked audit context rather than proof of freshness.
- **`resolve_preregistration` computes correction against the count of currently-open prereg rows.** Locking many preregs at once intentionally tightens alpha, which is conservative multiple-comparison behavior. In the current v3.0-compatible implementation, `bh` and `bonferroni` are aliases for the same Bonferroni-style calculation.

### 11. Resource ledger (v3.0)

The resource budget mechanism is small but tightly specified.

- **`res_budget_ledger` rows are unique per `(scope, resource, window)`.** Currently four resources are tracked: `wallclock_sec`, `llm_tokens`, `heldout_queries`, `disk_mb`.
- **`budget_consume` is the only writer.** Overflow attempts return `{ok: False, error: "budget_exceeded"}` and emit a `budget_exceeded` cockpit event; callers must decide whether to halt or escalate.
- **`budget_check` is read-only and never decrements.** It must check the same `(scope, resource, window)` boundary that `budget_consume` writes, otherwise the two will disagree at the boundary.

### 12. Hook chain

Hooks are the mechanical guarantees of the system. They run as short-lived subprocesses spawned by Claude Code at lifecycle events.

| Event | Hook | Effect |
|---|---|---|
| `PreToolUse` (Write/Edit/Bash) | `leakage_guard.py` | Denies any tool call whose path resolves into a held-out directory |
| `PreToolUse` (Bash) | `destructive_bash_guard.py` | Denies destructive commands unless the marker `# CONFIRM_DESTRUCTIVE` appears |
| `PostToolUse` (Bash) | `provenance_log.py` | Extracts numeric tokens from stdout into `ver_provenance` |
| `UserPromptSubmit` | `intervention_pump.py` | Drains `cockpit_interventions` into `additionalContext` for the next main-agent turn |
| `Stop` | `intervention_pump.py` + `stop_flush.py` | Same drain, plus a `turn_end` event |

Hooks must be idempotent and must degrade gracefully when the database is missing or malformed (typical case: first run, no DB yet). Missing state means "no intervention pending", not "crash".

Cockpit interventions are not a live interrupt mechanism. If the main agent
has already spawned a long-running subagent or tool call, an intervention
entered in the TUI waits in `cockpit_interventions` until Claude Code fires
the next `UserPromptSubmit` or `Stop` hook.

`cockpit_events` is append-only during normal operation. Long-running
sessions can prune old UI events explicitly with
`uv run python -m cockpit.tui --prune-events 50000`, which preserves the
newest N rows and leaves report files / report index rows untouched.

### 13. Core vs domain trunks (v4.0)

ClaudeScientist v4.0 separates the architecture into a **shared core** and **two domain trunks** on top. The split is formally documented in [ADR 0008](adr/0008-two-trunk-domain-architecture.md); this section maps which existing surface is which, and what v4.0 adds.

#### What is in the shared core

The core is everything that doesn't know whether the work in flight is empirical or theoretical. It's the moat — both trunks compound through it, and a single failure ledger across both is one of v4.0's real differentiators.

| Surface | Component | Why it is core |
|---|---|---|
| `claudescientist.runtime` | path, SQLite, migrations, event emission | Domain-free infrastructure |
| `mem_nodes` / `mem_edges` | hypothesis/proposition graph | `kind` field carries the domain; the table itself does not |
| `mem_failures` + FTS5 | cross-domain failure ledger | New `domain` column gates filtering; the matching algorithm is domain-free |
| `mem_bt_ratings` + tournament tools | ranking + LUCB intervals | Cross-kind comparison stays disallowed; same-kind comparison works for `hypothesis` and `proof_skeleton` alike |
| `meta_calibration` | per-agent reliability | Calibration is per-judge, not per-domain |
| `mem_replay_branches` | counterfactual snapshots | Domain-free |
| `cockpit` + `cockpit_events` | live UI + event bus | One tree, two trunks |
| Hooks: `destructive_bash_guard`, `intervention_pump`, `stop_flush` | safety + lifecycle | Domain-free |

#### What is in the empirical trunk

| Surface | File / table | Notes |
|---|---|---|
| `verify_mcp` | leakage / heldout / seed_perturb / baseline_fairness / preregistration / provenance DAG / pin_metric / budget | Existing v3.0 toolset |
| Hooks: `leakage_guard.py`, `provenance_log.py` | `.claude/hooks/` | ML-specific (held-out paths, metric extraction) |
| Agents: engineer, verifier | `.claude/agents/` | ML-specific roles |

These tools and agents are tagged `[empirical]` in the per-module maps. A proof-only user will see them in the catalogue but should not need to invoke them.

#### What is in the proof trunk

New in v4.0; lives in [`src/prove_mcp/`](../src/prove_mcp/):

| Surface | Notes |
|---|---|
| `prv_corpus_problems`, `prv_corpus_keywords` | StatEval-style retrieval corpus, dual lexical+semantic keywords with embeddings |
| `prv_diagnostic_manifests` | snippet-level diagnosis output |
| `prv_lean_attempts` | tracks every Lean formalisation attempt regardless of outcome |
| Tools | `ingest_proof_corpus`, `retrieve_skeletons`, `segment_proof`, `diagnose_snippet` (queries `mem_failures` with `domain='proof'`), `apply_correction`, `triage_for_formalization` |
| Agents | prover (the v0.1 stub is activated against `lean-lsp-mcp`) |
| Skills | `prove-sop` |
| External MCP | `lean-lsp-mcp` registered alongside `arxiv` / `openalex`; only invoked when triage rules pass |

#### The four cooperation interfaces

The two trunks compose through exactly four shared interfaces, no more. Anyone tempted to add a fifth should write a superseding ADR first.

1. **One tree.** `mem_nodes.kind` accepts `proposition`, `proof_skeleton`, and `proof_snippet` as well as the empirical kinds. A proposition can sit as a sibling of a hypothesis under the same question.
2. **One failure ledger.** `mem_failures.domain` partitions records by domain; `match_signatures` accepts an optional `domain` filter and defaults to cross-domain. An off-by-one signature stored from a script crash can match an off-by-one signature in a proof snippet.
3. **One tournament.** BT comparison accepts both `hypothesis` and `proof_skeleton` kinds (same-kind only). Cross-kind comparison is forbidden to keep semantics clean.
4. **One reviewer, two checklists.** `reviewer.md` switches its checklist by manuscript content: empirical central claims use the relevant anchors (pin / seed verdict / met preregistration for confirmatory claims / non-stale provenance); theorem claims add an empty diagnostic manifest plus either a Lean verification or an explicit `unverified` flag. The `unverified` flag is a manuscript-level annotation, not a `prv_diagnostic_manifests.status` value.

`prove_mcp.tools.nodes` is the only sanctioned writer from the proof trunk into the shared graph tables (`mem_nodes`, `mem_edges`, and proof-skeleton `mem_bt_ratings` seeds). That narrow exception keeps the one-tree interface real without turning the rest of `prove_mcp` into a memory-table owner.

#### Reading the per-module map labels

`src/memory_mcp/__init__.py` and `src/verify_mcp/__init__.py` tag every public tool and every owned table with one of three labels:

- `[core]` — domain-agnostic; usable from either trunk.
- `[empirical]` — only meaningful in the empirical workflow.
- `[proof]` — added in v4.0, lives in `prove_mcp`.

When a contributor changes a tool or table, the label tells them which trunks they need to re-test.

#### Snapshot scope across trunks

`memory_mcp.snapshot()` writes a payload that covers both trunks so a counterfactual `replay_counterfactual` against a proof branch can reconstruct enough state:

- `active_frontier` includes `proposition` alongside `question` / `hypothesis`.
- `proof_drafts` / `proof_manifests` / `proof_lean_attempts` capture recent rows from `mem_nodes(kind='proof_skeleton')`, `prv_diagnostic_manifests`, and `prv_lean_attempts`.
- `counts.proof_corpus` is the size of `prv_corpus_problems`.
- Every `prv_*` read is wrapped in `sqlite3.OperationalError` so a v3.0-only DB (no proof schema yet) snapshots cleanly with empty proof sections.

`stop_flush.py` digests follow the same pattern: the per-turn summary includes `proof_manifests_*`, `lean_attempts_*`, and `lean_wallclock_used_sec` aggregates, with the same legacy-DB fallback.

#### Budgeter coverage

The proof trunk obeys the same `verify_mcp.budget_check` / `budget_consume` gating that the empirical trunk uses. Both `.claude/agents/prover.md` § Budget and the `prove-sop` skill require:

1. Estimating wallclock cost from `prove_mcp.triage_for_formalization`'s `estimated_difficulty`.
2. Calling `budget_check(scope='hypothesis:<proposition_id>', resource='wallclock_sec', requested=<estimate>)` before longer Lean attempts (>= 5 minutes). Low-cost attempts may proceed with an audit warning when no budget is configured.
3. Calling `budget_consume` with the actual `duration_sec` after the attempt completes, so `res_budget_ledger` and `prv_lean_attempts` stay consistent.

A `record_lean_attempt(status='timeout')` without a prior `budget_check` is an audit warning. Missing budget context does not invalidate the NL proof itself.

### 14. Cockpit activity streaming (v5.0)

v5.0 rearranges the cockpit's information surface so the primary read
mode answers "what is the agent doing right now / does anything need
my attention / what just changed" rather than "what atomic operation
just fired". The change is presentation-only: the underlying `cockpit_events`
table, its emission contract, and the per-MCP-server payload schemas are
unchanged. See [ADR 0011](adr/0011-cockpit-activity-streaming.md) for
the full rationale + alternatives.

#### Five-layer surface

| Layer | Source | Question it answers |
|---|---|---|
| Phase strip (top dock) | `cockpit.phase.derive_phase` over last 200 events | "What now?" |
| Activity pane (grid main) | `cockpit.activity.aggregate` over last 30 min | "What just happened at the research level?" |
| Focus tab (RightTabsPane, first tab) | `cockpit.panes.focus_pane.derive_focus` over last 2 min | "Which node is the agent working on?" |
| Other tabs (Risks / Failures / Claims / Lit / Reports / Corpus / Diagnostics / Lean) | `cockpit.data` fetches | "What can I query?" |
| Audit log (bottom dock, hidden until `a` / `A`) | EventStreamPane verbatim | "What atomic operations fired?" |

Each derivation is a pure function over `cockpit_events` rows. No new
table is introduced — phase / focus / activity are recomputed every
tick. This honors [ADR 0007](adr/0007-tools-skills-hooks-layering.md)'s
"workflow state inferred from data, not stored" rule.

#### Phase vocabulary

Eight phases, ordered roughly by SOP progression:

- `idle` — no activity in the window (default after 90 s silence)
- `explore` — `graph_delta` / `literature_ingested` dominate
- `select` — `judgement_recorded` / `bt_rating_updated` / `branch_*` dominate
- `experiment` — `failure_added` / redirect-class `intervention`
- `verify` — `seed_run_recorded` / `prereg_*` / `heldout_query_*` / `budget_exceeded` / `prov_dag_stale`
- `prove` — `proof_*` / `lean_*`
- `review` — `claim_pinned` / `report_generated` / `snapshot_created` / `replay_branch_created`
- `narrate` — `agent_narration` without any of the above

Explicit `phase_set` events (emitted by `cockpit__set_phase`) override
derivation when present and recent.

#### Activity card families

| Family | Glyph | Kinds |
|---|---|---|
| graph | ◇ | `graph_delta`, `branch_paused`, `branch_pause_suggested`, `branch_promoted`, `auto_prune`, `literature_ingested` |
| bt | ⚖ | `bt_rating_updated`, `judgement_recorded` |
| verify | ✓ | `seed_run_recorded`, `prereg_*`, `heldout_query_*`, `claim_pinned`, `snapshot_created`, `report_generated`, `replay_branch_created` |
| prove | ⊢ | `proof_*` |
| lean | λ | `lean_proof_*` (kept separate for source-preview rendering) |
| intervention | ! | `intervention`, `intervention_undone` |
| narrate | " | `agent_narration`, `note`, `phase_set` |
| risk | ▲ | `budget_exceeded`, `prov_dag_stale`, `failure_added` (singletons) |

Cards group by `(family, focus_node_id)` when the payload names a node,
or by `(family, 60-second bucket)` for high-volume kinds without a
target (currently `proof_corpus_reindex_progress`). `budget_exceeded`,
`prov_dag_stale`, `failure_added`, `agent_narration`, `phase_set`, and
`note` are always singleton cards so individual signals never get
swallowed by aggregation.

#### Severity bands

| Severity | Glyph | Kinds (default; payload-aware overrides apply) |
|---|---|---|
| critical | ■ | `budget_exceeded`, `prov_dag_stale` |
| high | ▲ | `lean_proof_failed`, `branch_paused`, `failure_added`, `intervention.halt`, `prereg_resolved(unmet)`, `heldout_query_finished(failed)` |
| medium | ● | `prereg_resolved`, `proof_diagnosis_recorded(is_flawed=True)`, `branch_pause_suggested`, `intervention*` |
| low | · | `note`, `agent_narration`, `bt_rating_updated`, `proof_corpus_reindex_progress`, `report_generated`, `phase_set` |
| info | (blank) | everything else |

Cards display the maximum severity of their constituent events. The
severity glyph plus colour give a redundant signal so red-green
colour-blind users can still distinguish via shape.

#### Cockpit MCP tools (v5.0 additions)

Two new atomic verbs in `cockpit.mcp_server`:

- `cockpit__set_phase(phase, focus_nodes, intent)` — writes one
  `phase_set` event. Validates phase against the 8-name vocabulary;
  caps `focus_nodes` to 8 entries each matching `^[a-z]+_[a-z0-9_]+$`;
  truncates `intent` to 200 chars.
- `cockpit__narrate(text, scope)` — writes one `agent_narration`
  event. Text 1-500 chars after strip; scope matches `^(session|node:<id>|branch:<id>)$`.

Both tools are descriptive: agents that never call them work
identically; the cockpit's derivation handles the absence gracefully.
Worker agents (`researcher`, `engineer`, `prover`) carry them in their
`tools:` whitelist; query-only agents (`librarian`, `verifier`,
`reviewer`, `budgeter`) do not.

#### Settings interaction

- `CockpitSettings.phase_strip_visible: bool = True` — toggled by `P`.
- `CockpitSettings.animations_enabled: bool = True` — toggled by `M`;
  adds an `animations-off` class to the screen for future TCSS
  `transition` opt-outs.
- Legacy `focused_pane="events"` from pre-v5 installs is healed to
  `"activity"` at boot, matching the existing `LAYOUT_FOCUS → wide`
  healing pattern in `app.py`.

### 15. Per-module maps

This document covers cross-module contracts. Each module's `__init__.py` (or `README.md`, for the hooks directory) carries a structured map of its public surface, owned tables, invariants, and "do not" rules. Read those before making non-trivial changes inside a module:

- [`src/claudescientist/__init__.py`](../src/claudescientist/__init__.py)
- [`src/memory_mcp/__init__.py`](../src/memory_mcp/__init__.py)
- [`src/verify_mcp/__init__.py`](../src/verify_mcp/__init__.py)
- [`src/cockpit/__init__.py`](../src/cockpit/__init__.py)
- [`.claude/hooks/README.md`](../.claude/hooks/README.md)
