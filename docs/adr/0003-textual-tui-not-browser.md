# ADR 0003: Drop the browser frontend; adopt a Textual TUI

- **Status**: Accepted (v0.2)
- **Date**: 2026-04

## Context

The v0.1 cockpit shipped a browser UI: FastAPI + uvicorn for the backend,
WebSocket for live state, React 19 + Vite 8 + Tailwind v4 + `@xyflow/react`
for the frontend. To render roughly twenty hypothesis nodes, fifty
failures, a small event stream, and one intervention form, this stack
required:

- two extra processes the user had to start (uvicorn + Vite dev server)
- a Node.js dependency separate from the Python toolchain
- a port choice (7777) that occasionally collided with other dev servers
- ~2.5k lines of TypeScript plus its node_modules tree

The user's own report on v0.1 was "架构不稳定 / 重 / 不协调" - the UI was
demonstrably overpowered for the data it rendered.

Meanwhile, mature TUI frameworks (Textual, in particular, by the Rich
author) had reached the point where keyboard-first dashboards like k9s and
lazygit are not only viable but preferred for single-user workflows.

## Decision

Replace the entire browser cockpit with a **Textual TUI** that runs in a
second terminal next to Claude Code:

```powershell
uv run python -m cockpit.tui
```

The TUI reads SQLite via a 1-second poll loop, writes interventions back
to `cockpit_interventions`, and offers English / Chinese label switching
through `cockpit.i18n`. The browser frontend tree (`src/cockpit/frontend/`)
is deleted entirely. FastAPI and uvicorn drop out of `pyproject.toml`.

## Consequences

### Positive

- One Python toolchain, one process model. `uv sync` is enough to run
  everything; no Node.js install, no `pnpm install`, no Vite.
- Net deletion of ~2.5k lines of frontend code plus the FastAPI sub-app.
- The dashboard runs over SSH, on remote dev boxes, in tmux - anywhere
  Python runs.
- Keyboard-first muscle memory matches the rest of the user's tooling
  (vim, k9s, lazygit).

### Negative

- No mouse-driven interaction (Textual supports mouse, but we do not
  invest there).
- No multi-user / shared-screen view. Acceptable: ClaudeScientist is
  explicitly a single-user tool.
- Some visualisations that are easy in `@xyflow/react` (force-directed
  graph layouts, smooth pan / zoom) are not feasible in a TUI. We mitigate
  by using the Textual `Tree` widget as the navigation spine and showing
  cross-edges in a detail panel.
- Anyone who liked the browser will not get it back. Re-introducing it
  would require re-adopting the FastAPI / uvicorn dependencies and is
  explicitly out of scope per the v3.1 roadmap.

### Alternatives considered

- **Keep the browser, polish it** - lost because the polish work was
  estimated at multiple weeks and would not address the daemon-burden
  complaint.
- **Switch to a different web framework (Streamlit, NiceGUI)** - lost
  because the daemon burden persists and we still need a Node-side build
  step for any custom widgets.
- **Drop the cockpit entirely; use logs** - lost because real-time
  observation of long sessions is the whole point.

## References

- Originating discussion: [`docs/archive/plan-v0.2.md`](../archive/plan-v0.2.md)
  sections 1, 2.1, 4, and 5.
- Implementation: [`src/cockpit/`](../../src/cockpit/).
- Documented expectation: [`README.md`](../../README.md) ("The cockpit is
  terminal-first").
