# Archive

> Chinese version: [README.zh-CN.md](README.zh-CN.md)

This directory holds the historical planning documents that drove
ClaudeScientist from an empty repository to its current shape. Every plan in
this folder has already been delivered; the source of truth for what the
system does today lives one level up in `docs/`, not here.

These files are kept because they record **why** certain decisions were made,
not just what was built. When a later contributor wonders "why is the cockpit
a TUI instead of a browser app", the answer lives in `plan-v0.2.md`. When
they wonder "why did we replace Elo with Bradley-Terry", the answer lives in
`plan-v3.0.md`. Deleting these files would erase the reasoning trail.

## Reading order

If you want the full chronological story:

1. **[`original-ideas.zh-CN.md`](original-ideas.zh-CN.md)** — the two-line
   brainstorm that seeded the project. Both improvements proposed here ended
   up shipped in v3.0.
2. **[`plan-v0.1.md`](plan-v0.1.md)** / [`plan-v0.1.zh-CN.md`](plan-v0.1.zh-CN.md)
   — the first detailed plan. Contains the original architecture decisions
   (single SQLite file, per-component table prefixes, `uv` for everything),
   plus a now-obsolete browser cockpit built on FastAPI + React + Vite. The
   browser frontend was deleted in v0.2; everything else from v0.1 still
   stands.
3. **[`plan-v0.2.md`](plan-v0.2.md)** / [`plan-v0.2.zh-CN.md`](plan-v0.2.zh-CN.md)
   — the pragmatic refactor. Removes the entire Web UI in favor of a Textual
   TUI, and adds three verification capabilities: `seed_perturb`, Elo-based
   hypothesis selection, and held-out budget enforcement.
4. **[`plan-v3.0.md`](plan-v3.0.md)** — the statistical-rigor pass. Replaces
   Elo with Bradley-Terry, introduces preregistration with BH/Bonferroni
   correction, adds a refreshable provenance DAG, and gates auto-pruning
   behind an opt-in environment variable. This is the version currently
   shipping.

## What lives outside this archive

Anything in `docs/` that is **not** under `archive/` describes the system as
it stands today:

- `docs/overview.md` — the five-minute mental model
- `docs/architecture.md` — cross-module contracts and invariants
- `docs/tool-reference.md` — the full v3.0 MCP tool catalog
- `docs/workflows/` — scenario-driven walkthroughs

If you find a contradiction between an archived plan and a current document,
the current document wins. Please open an issue so the archive can be
annotated, but do not "fix" the archive — these files are immutable history.

For the distilled rationale of each major decision (one page each, easier
to scan than the long plans), see [`../adr/`](../adr/).
