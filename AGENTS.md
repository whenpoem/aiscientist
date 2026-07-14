# AGENTS.md

> 中文版本: [AGENTS.zh-CN.md](AGENTS.zh-CN.md)
> Operating instructions for any later LLM or coding agent working in this repository. For project orientation and architecture, read [`README.md`](README.md) and [`docs/overview.md`](docs/overview.md) first — this file assumes you already know what the project does.

## Editing rules

- **Prefer small, explicit changes over broad rewrites.** This repository is small enough that rewrites are tempting and almost always wrong.
- **Keep Windows compatibility.** The target machine is Windows 11. Prefer ASCII unless the file already requires otherwise.
- **If you change behavior, update or add tests in the same area.** Behavioral changes without test updates are regressions waiting to happen.
- **Do not claim a fix works until you rerun the relevant command.** "Should work" is not the same as "works".
- **Do not say "production-ready" based only on unit tests.** Unit-test green is necessary, not sufficient.
- **Do not modify files in `.research-agent/`.** That directory is runtime state, not source. Use the MCP tools to mutate it.
- **Do not bypass `query_heldout`** to read sequestered data. The leakage hook will block you anyway, and bypassing it leaves an audit gap.

## Verification rules

Before claiming success, run the checks that match the change.

Minimum baseline:

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/prove_mcp tests/hooks tests/cockpit tests/scripts tests/e2e
```

If cockpit code changed, also smoke-test the TUI entrypoint:

```powershell
uv run python -m cockpit.tui --once
uv run python -m cockpit.tui --once --lang zh
```

If integration points changed, also smoke-test the backend:

```powershell
uv run python -c "import memory_mcp.server; import verify_mcp.server; import prove_mcp.server; import cockpit.mcp_server; print('OK')"
```

## What to read before a non-trivial change

In this order:

1. [`README.md`](README.md) — orientation
2. [`docs/overview.md`](docs/overview.md) — mental model
3. [`docs/architecture.md`](docs/architecture.md) — cross-module contracts (treat as binding)
4. [`.claude/settings.json`](.claude/settings.json) — MCP and hook wiring
5. The relevant package under `src/`
6. The matching tests under `tests/`
7. [`docs/archive/`](docs/archive/) only if the change is about historical scope

## MCP and tooling notes

The Claude settings are already wired for these MCP servers: `memory`, `verify`, `cockpit`, `arxiv`, `openalex`. Two specifics that occasionally surprise people:

- **`openalex-research-mcp` is launched via `npx -y openalex-research-mcp@0.5.0`**, not `uv`, because the real package is a Node CLI in this environment.
- **The cockpit MCP runs over stdio** through `uv run python -m cockpit.mcp_server`. There is no HTTP transport.

If you change `.claude/settings.json`, assume Claude Code will need a fresh session to reload MCP and hooks.

## Database and state notes

Shared runtime state lives in `.research-agent/state.db` by default, or wherever `RESEARCH_AGENT_DB_PATH` points if you have overridden it. The same database is used by:

- memory MCP
- verify MCP provenance storage
- cockpit event and intervention flow
- hooks (`intervention_pump.py`, `stop_flush.py`, etc.)
- sequestered dataset registration and budget counters

Do not delete or overwrite the DB casually during debugging. If a test needs isolation, use the test fixtures rather than mutating the real state file.

## Known fragile areas

- **Hook behavior depends on shared state files.** If `.research-agent/state.db` or the stop-flush state file is missing or malformed, some protections degrade to permissive or fallback behavior.
- **The cockpit live view polls.** It reads SQLite events on a 1-second cadence. It is simple and works, but it is not a high-throughput design.
- **Sequestered dataset protection has multiple inputs.** It depends on `RESEARCH_AGENT_HELDOUT_DIR`, registered `ver_heldout_budgets.heldout_path` rows, pointer files, and `leakage_guard.py`. Do not bypass any of these by reading the data directly; use `query_heldout`.
- **Cockpit UI labels must go through `src/cockpit/i18n.py`** so English and Chinese modes stay aligned. Hard-coded strings inside widgets are a regression.

## Git context

The default branch in this checkout is `claudescientist`, which has been pushed to:

- `https://github.com/whenpoem/aiscientist.git`

Do not assume a PR exists unless you verify it. Do not force-push the branch unless asked.

## Scope reality

This repository has shipped the v3.0 plan ([`docs/archive/plan-v3.0.md`](docs/archive/plan-v3.0.md)). Do not casually rename that to "V1.0 complete" or "production-ready" without verifying the remaining product and operations expectations yourself.

**v5.1.1 is the current version.** It fixes the public marketplace so the
plugin source is pinned to the same release tag. The v5.1 line adds order-invariant full-ledger BT MAP
refits with explicitly uncalibrated intervals, fixed preregistration families,
automatic code/Git/runtime manifests, protection-strength labels, installation
root versus workspace root separation, a portable public Codex plugin, the
`claudescientist` CLI/doctor, and expanded core Skills. The public plugin keeps
Cockpit monitoring and intervention; intervention is monitor-only until Codex
trusts its hooks. Core MCPs are enabled by default; arXiv, OpenAlex, and Lean are
opt-in. v5.0's activity-streaming Cockpit remains the current UI architecture;
see [ADR 0011](docs/adr/0011-cockpit-activity-streaming.md).

**v4.2.0 was the prior version.** v4.2 landed across four alphas: a0 added multi-provider support to the vector backend and polished the setup wizard; a1 refitted the cockpit's information architecture (tab grouping, collapsible detail sections, pane-scoped keys); a2 added reports infrastructure (`cockpit.export` module with five report kinds × two formats, Reports tab, ExportModal, `verify_mcp.export_report` tool); a3 added a cold-start Welcome screen. Dense content (closure certificates, full drafts, diagnostic manifests, portfolio comparisons, cascade traces) is exported as markdown / HTML files under `reports/` per [ADR 0009](docs/adr/0009-reports-as-files-monitoring-as-tui.md). The vector backend accepts any OpenAI-compatible endpoint via `RESEARCH_AGENT_EMBED_BASE_URL` (DashScope / Jina / Voyage / GLM tested) per [ADR 0010](docs/adr/0010-multi-provider-embeddings.md); the default local model is `Qwen/Qwen3-Embedding-0.6B`; corpus rows carry a `(backend, model, dim)` triple. The proof trunk shipped in v4.0: `prove_mcp` MCP server, `prove-sop` skill, `prover` agent definition, cold-start seed scripts in `scripts/`, and the reviewer dual checklist. Lean reinsurance remains opt-in: `_lean` in `.claude/settings.json` is disabled until the user manually installs elan + mathlib + lean-lsp-mcp per [`docs/setup-lean.md`](docs/setup-lean.md). See [ADR 0008](docs/adr/0008-two-trunk-domain-architecture.md) for the two-trunk architecture, [ADR 0007](docs/adr/0007-tools-skills-hooks-layering.md) for the layering doctrine, and [architecture.md §13](docs/architecture.md#13-core-vs-domain-trunks-v40) for the core/trunk split.

For the complete current scope and the full MCP tool list, see [`docs/tool-reference.md`](docs/tool-reference.md).
