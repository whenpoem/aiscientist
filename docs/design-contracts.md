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
