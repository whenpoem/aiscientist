# ADR 0001: Single SQLite file as the only state boundary

- **Status**: Accepted (v0.1)
- **Date**: 2026-04

## Context

ClaudeScientist is composed of four runtime layers (memory MCP, verify MCP,
cockpit, hooks) plus several short-lived hook subprocesses. They all need
shared state: hypothesis graph, failure ledger, pinned metrics, cockpit
events, intervention queue. Each subprocess must be able to read whatever
the others have written, including the cockpit displaying a hypothesis
created by Claude in the same second.

The obvious alternatives at the time were: (a) one SQLite file per
component with cross-process IPC for joins; (b) Postgres with a daemon;
(c) a Redis-style in-memory store with periodic snapshots.

The deliverable is a tool a single researcher runs locally on Windows. The
state must be `cp`-able, the install must require zero daemons, and a
fresh checkout must start working with no setup beyond `uv sync`.

## Decision

All local runtime state lives in **one** SQLite file at
`.research-agent/state.db`. Each component owns its own tables under a
prefix (`mem_*`, `ver_*`, `res_*`, `cockpit_*`, plus shared `ra_migrations`
and `meta_*`). WAL mode is enabled so the cockpit can read while memory and
verify write. Every component connects through
`claudescientist.runtime.connect_sqlite()` so the connection settings stay
identical.

## Consequences

### Positive

- One file to back up. One file to delete to start fresh.
- Cross-component atomic operations (e.g. "create hypothesis AND seed BT
  rating row AND emit cockpit event") are naturally one SQL transaction.
- WAL mode keeps multi-process throughput acceptable at our scale.
- Hooks running as one-shot subprocesses can `sqlite3.connect(state.db)`
  in milliseconds; they pay no daemon cost.
- The cockpit's poll-and-render loop is trivially expressible as
  `SELECT id > last_seen FROM cockpit_events`.

### Negative

- All schema changes touch the same migration ledger; we must coordinate
  versions across components instead of letting each evolve independently.
- High-throughput writes from many concurrent agents would eventually hit
  WAL contention. Acceptable at single-user scale; not acceptable for
  multi-tenant deployment, which we explicitly do not target.
- Cross-component coupling is implicit (any component can read any table).
  Discipline is enforced by the architecture doc, not by the database.

### Alternatives considered

- **One SQLite per component, IPC for joins** - lost because the cockpit
  would need to join across three files for every render, and we would
  invent a custom IPC protocol just to recover what SQL gives us free.
- **Postgres with a daemon** - lost because it adds an installation step
  and a process to remember to start. Wrong scale.
- **Redis snapshots** - lost because we need durable history (provenance,
  failure ledger), not a fast cache.

## References

- Originating discussion: [`docs/archive/plan-v0.1.md`](../archive/plan-v0.1.md)
  section 4.2 ("Key decision A - State sharing").
- Implementation: [`src/claudescientist/runtime.py`](../../src/claudescientist/runtime.py).
- Cross-component contract: [`docs/architecture.md`](../architecture.md) section 3.
