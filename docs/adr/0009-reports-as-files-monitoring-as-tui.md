# ADR 0009: Reports as files, monitoring as TUI

- **Status**: Accepted (v4.2)
- **Date**: 2026-05

## Context

The cockpit started as a thin live-state viewer in v0.2 and grew
through v4.0–v4.1 to handle hypotheses, the BT leaderboard, the
proof corpus, diagnostic manifests, Lean attempts, and seven tabular
views. v4.1.0a4 added a drill-in screen to absorb long content into
the TUI surface; v4.2.0a1 added tab grouping and Collapsible
sections to absorb the next round of growth.

Two pressures push past what the TUI is well shaped to carry:

1. **Dense structured reports.** Closure certificates, full LaTeX
   drafts, side-by-side proof-skeleton portfolios, cascade traces.
   These are document-shaped, not status-shaped. They want a viewer
   that can do hierarchy and reflow, not a 24-row scrolling pane.
2. **Sharing.** The reviewer agent, the writeup process, and an
   external collaborator all want to consume the same evidence
   snapshot. Embedding the content inside the cockpit makes that
   awkward — there is no stable handle to point at.

ADR 0003 closed the door on adding a browser UI to the cockpit. The
problem the cockpit is meant to solve (live monitoring + keyboard
intervention) is well served by a TUI, and the cost of running a web
server + a build pipeline alongside the TUI was repeatedly judged
too high.

The shape that satisfies both pressures without reopening ADR 0003
is **files written to disk, opened in the user's existing editor or
browser**. No daemon, no port, no JavaScript framework — the cockpit
writes markdown / HTML files and hands the path off to the user's
existing tooling.

## Decision

Reports become file artifacts written to `reports/<short-id>-<kind>.<format>`,
indexed in a new `cockpit_reports` table, and surfaced through three
cockpit affordances: a Reports tab, a Reports section in the detail
pane, and an `e` key on a selected node that opens the export modal.

The cockpit itself never embeds a renderer for the file formats.
Pressing Enter on a report row in the cockpit calls the OS's default
handler (`os.startfile` on Windows, `open` on macOS, `xdg-open` on
Linux). The cockpit is responsible for the live monitoring half of
the workflow; the user's existing markdown / HTML viewer is
responsible for the document-reading half.

The implementation is split into three layers — DTO, renderer,
pipeline — under `src/cockpit/export/`. Five report kinds ship in
v4.2 (closure, draft, diagnostic, portfolio, cascade) and two
formats (markdown, html). Each combination is reproducible from
SQLite alone: rerunning an export overwrites the previous file
deterministically.

The reviewer agent gains an optional `mcp__verify__export_report`
tool that calls the same pipeline. It never becomes a hard rule —
the reviewer's empirical and proof checklists from ADR 0006 and
ADR 0008 stay unchanged — but the reviewer may attach a closure
report path in its `notes` for the manuscript author's convenience.

## Consequences

### Positive

- The cockpit no longer fights to render content it was not designed
  for. Long draft text, full diagnostic manifests, and side-by-side
  portfolios all live in files the user opens with their preferred
  tool.
- Reports become shareable. The path is stable; the user can attach
  it to an issue, hand it to a collaborator, or explicitly force-add
  selected files to git without re-running the cockpit.
- The Reports tab gives the user a single index of what has been
  generated; the detail pane surfaces the same files under the node
  they describe.
- ADR 0003's no-web-UI position holds. The cockpit still runs as a
  pure TUI; the new files are read by the user's existing tooling,
  not by a new daemon.

### Negative

- The user has to manage the `reports/` directory. Files do not
  garbage-collect themselves. The directory is gitignored by default
  because reports can contain private results, held-out-derived
  metrics, and unpublished drafts; intentional sharing should use an
  explicit path or `git add -f reports/<file>`. The `cockpit_reports`
  table keeps rows after the file is deleted (with a ``missing`` flag)
  so the audit history survives; cleanup is a manual operation.
- Two surfaces show the same evidence: the cockpit's live tabs and
  the generated reports. The user has to learn which is which —
  monitoring vs. archive. We accept that as the cost of having a
  proper archive at all.
- The cockpit's drill-in into a report row is a one-way trip out of
  the TUI (it spawns the user's default app). That is the right
  shape for documents but breaks the "everything in one terminal"
  contract; users on a headless box should know markdown is the
  better default for them.

### Alternatives considered

- **Render the dense content inline in the TUI.** Lost because the
  growth curve is super-linear. The cockpit already needs Collapsible
  sections + drill-in to absorb v4.1's content. Each new content
  shape would force another structural refit.
- **Spin up a local web server.** Lost because ADR 0003's
  daemon-burden complaint is still load-bearing. A single-binary
  server that serves the files would solve sharing but cost the
  one-process model.
- **Embed a markdown / HTML renderer in the cockpit.** Lost because
  Textual's primitives are not made for document-grade layout. The
  cockpit would end up reimplementing a fraction of a browser at
  significant cost.
- **Push every export through the reviewer agent rather than a
  dedicated module.** Lost because the reviewer is one consumer
  among several. The CLI `python -m cockpit.export` lets the user
  generate reports without spawning an agent.

## References

- Plan: `C:\Users\whenpoem\.claude\plans\iridescent-snuggling-matsumoto.md`
- Sibling ADR: [`0003-textual-tui-not-browser.md`](0003-textual-tui-not-browser.md)
- Sibling ADR: [`0007-tools-skills-hooks-layering.md`](0007-tools-skills-hooks-layering.md)
- Reviewer integration: [`../../.claude/agents/reviewer.md`](../../.claude/agents/reviewer.md)
- Implementation: `src/cockpit/export/`, `src/cockpit/db.py`,
  `src/cockpit/panes/tabs_pane.py`, `src/cockpit/modals/export.py`,
  `src/verify_mcp/tools/reporting.py`.
