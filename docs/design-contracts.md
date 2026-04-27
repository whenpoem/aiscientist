# Design Contracts

This repo is intentionally small, but several modules share runtime state. Keep
these contracts stable unless a migration and matching tests change them.

## Shared Runtime

- `claudescientist.runtime` owns project-local paths, SQLite connection setup,
  schema migration bookkeeping, held-out root resolution, and cockpit event
  insertion.
- Feature packages should not duplicate path resolution for shared resources.
  In particular, held-out data roots must come from `runtime.heldout_root()` or
  registered `ver_heldout_budgets.heldout_path` rows.

## SQLite State

- `.research-agent/state.db` is the single local state boundary for memory,
  verification, cockpit, and hooks.
- Every component still owns its own tables, but cross-component signals should
  go through `cockpit_events`.
- `ra_migrations` records the component schema version, schema hash, apply
  status, and failure text. Structural upgrades that cannot be expressed by
  `CREATE TABLE IF NOT EXISTS` should use explicit compatibility helpers and
  tests.

## Cockpit Events

- Producers should emit an event in the same transaction as the state change
  when the cockpit needs to update live.
- Current live events include graph changes, failures, pinned claims, seed-run
  updates, literature ingestion, and held-out query lifecycle events.
- The TUI may always refresh manually, but normal workflows should not depend on
  manual refresh to discover important state changes.
- User-facing cockpit labels should go through `cockpit.i18n` so English and
  Chinese modes stay aligned.

## Held-Out Data

- Direct file access to held-out data is blocked by hooks.
- `query_heldout` is the only intended access path. It reserves budget before
  running the model script, records a query row, and does not return raw stdout
  or stderr because those streams may contain leaked labels or rows.
- Failed model executions still consume reserved budget because the script was
  already granted access to the held-out path.

## Agent Tool Contracts

- Agent prompts and tool whitelists are part of the architecture. When an MCP
  tool becomes part of the research workflow, update the relevant agent file and
  add a smoke assertion so the prompt cannot drift silently.
- The verifier role should have access to leakage, provenance, seed stability,
  baseline fairness, and held-out budget tools.

## V3.0 Bradley-Terry layer

- `mem_bt_ratings` is the canonical hypothesis ranking. `mem_nodes.elo_score`
  is kept only for backwards compatibility; new readers should prefer
  `mem_bt_ratings.strength`, `strength_var`, and `n_comparisons`.
- `record_judgement` is the only tool that should write to BOTH the legacy
  `mem_judgements` ledger and the new `mem_bt_comparisons` ledger.
  `update_bt_rating` writes only to the new ledger and accepts the broader
  source set (`llm_judge`, `metric_diff`, `user_intervention`, `reviewer_critic`).
- `suggest_pause_low_strength` is **dry-run by default**. The
  `RESEARCH_AGENT_AUTO_PRUNE=1` environment flag is the only way to flip
  `mem_bt_ratings.status` to `paused`. `resume_branch` is the only allowed
  reversal path.
- `replay_counterfactual` MUST NOT mutate `mem_nodes` or `mem_bt_ratings`. It
  only writes a row to `mem_replay_branches`.

## V3.0 Preregistration & Provenance DAG

- Every numeric claim that ends up in a manuscript should trace to a
  `ver_preregistrations.prereg_id` whose `status='met'` and a
  `ver_seed_runs.verdict='stable'`. The `reviewer` agent enforces this on
  write-up.
- `ver_provenance_dag.input_hashes` records the sha256 of every cited input
  file at record-time. `refresh_claim` re-hashes and emits
  `prov_dag_stale` events. Stale provenance must be considered a hard blocker
  for write-up.
- BH / Bonferroni correction in `resolve_preregistration` is computed against
  the count of *currently open* prereg rows. Locking many preregs at once
  intentionally tightens alpha.

## V3.0 Resource Ledger

- `res_budget_ledger` rows are unique per `(scope, resource, window)`.
- `budget_consume` is the only writer. Overflow attempts return
  `{ok: False, error: "budget_exceeded"}` and emit a `budget_exceeded` event;
  callers must decide whether to halt or escalate.
- `budget_check` is read-only, never decrements, and must check the same
  `(scope, resource, window)` boundary that `budget_consume` writes.
