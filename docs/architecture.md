# Architecture and Design Contracts

> 中文版本: [architecture.zh-CN.md](architecture.zh-CN.md)
> This document describes the cross-module contracts that must hold for the system to work correctly. Treat every section here as an invariant: change it only with a migration and matching tests.

## 1. Module map

ClaudeScientist is composed of four runtime layers and one shared state file.

| Layer | Package | Process model | Talks to |
|---|---|---|---|
| **Runtime core** | `claudescientist` | Library (no daemon) | All other layers |
| **Memory MCP** | `memory_mcp` | One stdio subprocess per Claude Code session | SQLite, Claude over stdio |
| **Verify MCP** | `verify_mcp` | One stdio subprocess per Claude Code session | SQLite, Claude over stdio |
| **Cockpit** | `cockpit` | TUI process (Terminal B) **+** stdio MCP bridge | SQLite |
| **Hooks** | `.claude/hooks/*.py` | Short-lived processes spawned by Claude Code at lifecycle events | SQLite |

The five layers never call each other directly. They communicate exclusively by reading and writing the shared SQLite file at `.research-agent/state.db`.

## 2. Shared runtime

The `claudescientist.runtime` module owns the four pieces of cross-module infrastructure that every layer depends on:

- **Path resolution.** `state_db_path()`, `heldout_root()`, and friends are the only legitimate way to locate shared resources. Feature packages must not duplicate path resolution; in particular, held-out roots must come from `runtime.heldout_root()` or from a registered `ver_heldout_budgets.heldout_path` row.
- **SQLite connection setup.** `connect_sqlite()` enables WAL mode, foreign keys, and a 5-second busy timeout. Always go through it instead of opening raw `sqlite3` connections.
- **Schema migration bookkeeping.** The `ra_migrations` table records, per component, the schema version, schema hash, apply status, and any failure text. Structural upgrades that cannot be expressed by `CREATE TABLE IF NOT EXISTS` must use explicit compatibility helpers and ship with tests.
- **Cockpit event insertion.** `emit_cockpit_event()` is the canonical way to push something to the cockpit. Producers should call it inside the same transaction as the underlying state change.

## 3. SQLite state contract

`.research-agent/state.db` is the **single local state boundary** for memory, verification, the cockpit, and hooks. Two rules:

1. **Each component still owns its own tables.** Use the prefix conventions: `mem_*`, `ver_*`, `res_*`, `cockpit_*`, plus the shared `ra_migrations` and `meta_*` tables.
2. **Cross-component signals go through `cockpit_events`.** Reach into another module's tables only for read-only inspection in tests.

### Live event kinds

The cockpit reacts to these event kinds today. Producers must include either `node_id`, `hypothesis_id`, or both in the JSON payload when relevant:

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

The cockpit may always refresh manually, but normal workflows should not depend on manual refresh to discover important state changes.

### User-facing labels

All cockpit-visible labels must go through `cockpit.i18n` so English and Chinese modes stay aligned. Hard-coded strings inside widgets are a regression.

## 4. Held-out data contract

Held-out data — typically test sets — is doubly protected. Both protections must hold for the contract to be intact.

- **Direct file access is blocked by hooks.** The PreToolUse hook `leakage_guard.py` denies any `Read`/`Write`/`Edit`/`Bash` whose path resolves into a registered held-out directory. The block is unconditional unless the env var `RESEARCH_AGENT_VERIFY=1` is set, which only `verify_mcp` is allowed to set.
- **`query_heldout` is the only intended access path.** It reserves budget *before* running the model script, records a query row, and **does not return raw stdout or stderr** because those streams may contain leaked labels or rows. Failed model executions still consume reserved budget, because the script was already granted access.

If a hook or tool anywhere needs to bypass these protections, the bypass must come with a written justification and an additional unit test.

## 5. Agent tool contracts

Agent prompts and tool whitelists are part of the architecture, not just configuration. Two rules:

1. **When an MCP tool becomes part of the research workflow, update the relevant agent file.** Add a smoke assertion that checks the tool name appears in the agent prompt, so the prompt cannot drift silently away from reality.
2. **The verifier role is the integration point for verification tools.** It must have access to leakage detection, provenance, seed stability, baseline fairness, and held-out budget tools. Other roles get a strict subset.

The current agent role assignments live in `.claude/agents/`. Treat them as part of the source of truth.

## 6. The Bradley-Terry layer (v3.0)

This is the hypothesis-ranking system that replaced the v0.2 Elo layer.

- **`mem_bt_ratings` is the canonical hypothesis ranking.** New readers should prefer `strength`, `strength_var`, and `n_comparisons`.
- **`mem_nodes.elo_score` is kept only for backwards compatibility.** Existing v0.2 readers (and the tree pane's trailing display) can still read it, but no new feature should depend on it.
- **`record_judgement` is the only tool that dual-writes** to both the legacy `mem_judgements` ledger and the new `mem_bt_comparisons` ledger. `update_bt_rating` writes only to the new ledger but accepts a broader source set: `llm_judge`, `metric_diff`, `user_intervention`, `reviewer_critic`.
- **`suggest_pause_low_strength` is dry-run by default.** The env var `RESEARCH_AGENT_AUTO_PRUNE=1` is the only way to flip `mem_bt_ratings.status` to `paused`. `resume_branch` is the only allowed reversal path.
- **`replay_counterfactual` must not mutate `mem_nodes` or `mem_bt_ratings`.** It only writes a row to `mem_replay_branches`.

### The math, briefly

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

## 7. Preregistration and the provenance DAG (v3.0)

These two mechanisms together enforce trustworthy numeric claims.

- **Every numeric claim that ends up in a manuscript should trace** to a `ver_preregistrations.prereg_id` whose `status='met'` and to a `ver_seed_runs.verdict='stable'`. The `reviewer` agent enforces this on writeup.
- **`ver_provenance_dag.input_hashes` records the sha256 of every cited input file at record time.** `refresh_claim` re-hashes and emits `prov_dag_stale` events on drift. **Stale provenance is a hard blocker for writeup.**
- **BH / Bonferroni correction in `resolve_preregistration` is computed against the count of currently-open prereg rows.** Locking many preregs at once intentionally tightens alpha, which is the correct multiple-comparison behavior — the more hypotheses you test in parallel, the higher the bar each one must clear.

## 8. Resource ledger contract (v3.0)

The resource budget mechanism is small but tightly specified.

- **`res_budget_ledger` rows are unique per `(scope, resource, window)`.** Currently four resources are tracked: `wallclock_sec`, `llm_tokens`, `heldout_queries`, `disk_mb`.
- **`budget_consume` is the only writer.** Overflow attempts return `{ok: False, error: "budget_exceeded"}` and emit a `budget_exceeded` cockpit event; callers must decide whether to halt or escalate.
- **`budget_check` is read-only and never decrements.** It must check the same `(scope, resource, window)` boundary that `budget_consume` writes, otherwise the two will disagree at the boundary.

## 9. Hook chain contract

Hooks are the mechanical guarantees of the system. They run as short-lived subprocesses spawned by Claude Code at lifecycle events. The contract:

| Event | Hook | Effect |
|---|---|---|
| `PreToolUse` (Write/Edit/Bash) | `leakage_guard.py` | Denies any tool call whose path resolves into a held-out directory |
| `PreToolUse` (Bash) | `destructive_bash_guard.py` | Denies destructive commands unless the marker `# CONFIRM_DESTRUCTIVE` appears |
| `PostToolUse` (Bash) | `provenance_log.py` | Extracts numeric tokens from stdout into `ver_provenance` |
| `UserPromptSubmit` | `intervention_pump.py` | Drains `cockpit_interventions` into `additionalContext` |
| `Stop` | `intervention_pump.py` + `stop_flush.py` | Same drain, plus a `turn_end` event |

Hooks must be idempotent and must degrade gracefully when the database is missing or malformed (typical case: first run, no DB yet). Failure to read state means "no intervention pending", not "crash".

## 10. What this contract intentionally leaves open

Some things are deliberately not fixed by this document, because they are expected to evolve:

- **The exact set of MCP tools.** New tools land in the existing memory and verify servers without requiring a new MCP server, per the v3.0 plan.
- **Cockpit pane layout.** The grid, modals, and keybindings can change as long as the data contract above holds.
- **Subagent prompts.** They can be revised freely, as long as the tool whitelist matches the role's contract (rule §5.1).
- **External literature MCPs.** `arxiv-mcp-server` and `openalex-research-mcp` are installed as-is; we own only the `ingest_paper` compression layer in `memory_mcp`.

## 11. When to break a contract

If a future change requires breaking one of the contracts above, the right procedure is:

1. Open an issue describing what breaks and why.
2. Write the migration that moves the database forward.
3. Update this document **before** writing the code.
4. Add or update the test that pins the new contract.

Silent contract changes are the highest-severity bug class in this project.
