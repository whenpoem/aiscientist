# Architecture Decision Records

Short, dated records of the foundational design decisions behind
ClaudeScientist. Each ADR distils the rationale of a single decision into
roughly one page so a later contributor (human or AI) can understand
**why** something is the way it is without reading the full version plan.

ADRs are **immutable history**: once accepted, an ADR is not edited. If a
decision is reversed, write a new ADR that supersedes the old one and link
it from both sides.

## Index

| # | Title | Status | Shipped in |
|---|---|---|---|
| [0001](0001-single-sqlite-state-boundary.md) | Single SQLite file as the only state boundary | Accepted | v0.1 |
| [0002](0002-cockpit-mcp-stdio.md) | Cockpit MCP runs over stdio, not HTTP | Accepted | v0.2 |
| [0003](0003-textual-tui-not-browser.md) | Drop the browser frontend; adopt a Textual TUI | Accepted | v0.2 |
| [0004](0004-elo-to-bradley-terry.md) | Replace Elo with Bradley-Terry ranking | Accepted | v3.0 |
| [0005](0005-auto-prune-opt-in.md) | Auto-prune is dry-run by default; opt-in via env var | Accepted | v3.0 |
| [0006](0006-preregistration-as-writeup-gate.md) | Preregistration correction aliases as the writeup gate | Accepted | v3.0 |
| [0007](0007-tools-skills-hooks-layering.md) | Tools / Skills / Hooks layering doctrine | Accepted | v4.0 |
| [0008](0008-two-trunk-domain-architecture.md) | Two-trunk domain architecture (empirical + proof) on a shared core | Accepted | v4.0 |
| [0009](0009-reports-as-files-monitoring-as-tui.md) | Reports as files, monitoring as TUI | Accepted | v4.2 |
| [0010](0010-multi-provider-embeddings.md) | Multi-provider embeddings via configurable base_url | Accepted | v4.2 |

## Writing a new ADR

1. Copy [`TEMPLATE.md`](TEMPLATE.md) to `NNNN-short-slug.md` where `NNNN` is
   the next four-digit number.
2. Fill in every section. Keep the whole document under one page; if it
   wants to be longer, you are explaining a project plan, not an ADR.
3. Set `Status: Proposed` while debating, `Accepted` once shipped, or
   `Superseded by ADR-NNNN` once retired.
4. Add a row to the Index table above.
5. Reference the ADR from the relevant code or doc with a one-line link.

## Why ADRs at all

The version plans in [`../archive/`](../archive/) are long and prescriptive.
They answer "what shipped". ADRs answer "why we chose this over the
alternative", in a form that is short enough to actually be read. AI
contributors in particular benefit from this: when a tool is asked to
"clean up" or "modernise" some code, the ADR is what stops it from
unwinding a deliberate decision.
