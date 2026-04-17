# AGENTS.md

This file is for any later LLM or coding agent working in this repository.

## What This Repo Is

`claudescientist` is a Research-Agent augmentation layer for Claude Code.

It currently provides:

- persistent SQLite-backed memory
- verification tools for leakage and provenance
- Claude hooks for intervention and safety checks
- a FastAPI + FastMCP cockpit backend
- a Vite/React cockpit frontend

This repo is usable for local development and integration work.
Do **not** describe it as "production-ready" without doing a fresh end-to-end check.

## Scope Reality

The implementation in this repo matches the plan labeled `v0.1 / Phase 0-6`.
Do not casually rename that to "V1.0 complete" unless you have verified the remaining product and operations expectations yourself.

Known scope limits to remember:

- The actual exposed verify tools are `leakage_check`, `record_provenance`, `check_provenance`, and `pin_metric`.
- The prover agent is still a stub. Lean MCP tools are not wired in this repo yet.
- `snapshot` persists memory state, but cockpit does not yet browse historical snapshots as a first-class UI.

## Important Paths

- Claude config: `.claude/settings.json`
- Claude agents: `.claude/agents/`
- Claude skills: `.claude/skills/`
- Claude hooks: `.claude/hooks/`
- memory MCP: `src/memory_mcp/`
- verify MCP: `src/verify_mcp/`
- cockpit backend: `src/cockpit/`
- cockpit frontend: `src/cockpit/frontend/`
- tests: `tests/`
- project plan: `wiggly-leaping-lerdorf.md`

## How Things Actually Run

### Python side

This repo uses `uv` and Python 3.11.

Common commands:

```powershell
uv run pytest tests/memory_mcp tests/verify_mcp tests/hooks tests/e2e
uv run ruff check
uv run uvicorn cockpit.server:app --port 7777
```

### Frontend side

Run from `src/cockpit/frontend`:

```powershell
npm ci
npm run dev
npm run build
```

Default local URLs:

- cockpit backend: `http://127.0.0.1:7777`
- cockpit frontend: `http://localhost:5173`
- cockpit MCP mount: `http://127.0.0.1:7777/mcp`

## MCP and Tooling Notes

The Claude settings are already wired for these MCP servers:

- `memory`
- `verify`
- `cockpit`
- `arxiv`
- `openalex`

Important detail:

- `openalex-research-mcp` is configured through `npx -y openalex-research-mcp`, not `uv`, because the real package is a Node CLI in this environment.
- The cockpit MCP is mounted over HTTP at `http://127.0.0.1:7777/mcp`.
- The frontend lockfile is the contract. Use `npm ci`, not an unlocked `npm install`, unless you are intentionally updating the pinned stack.

If you change `.claude/settings.json`, assume Claude Code may need a fresh session to reload MCP and hooks.

## Database and State Notes

Shared runtime state is stored in:

- `.research-agent/state.db` by default, or `RESEARCH_AGENT_DB_PATH` when explicitly overridden

This state is used by:

- memory MCP
- verify MCP provenance storage
- cockpit event/intervention flow
- hooks such as `intervention_pump.py`

Do not delete or overwrite the DB casually during debugging.
If a test needs isolation, use the test fixtures rather than mutating the real state file.

## Editing Rules For Later Agents

- Prefer small, explicit changes over broad rewrites.
- Keep Windows compatibility.
- Use ASCII unless the file already needs something else.
- If you change behavior, update or add tests in the same area.
- Do not claim a fix works until you rerun the relevant command.
- Do not say "production-ready" based only on unit tests.

## Verification Rules

Before claiming success, run fresh checks that match the change.

Minimum usual checks:

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/hooks tests/e2e
```

If frontend code changed, also run:

```powershell
npm run build
```

If integration points changed, also smoke-test the backend:

```powershell
uv run python -c "import memory_mcp.server; import verify_mcp.server; from cockpit.server import app; print('OK')"
```

## Known Fragile Areas

- Hook behavior depends on the shared state DB and stop-flush state file under `.research-agent/`; if those files are missing or malformed, some protections degrade to permissive or fallback behavior.
- The cockpit websocket uses polling against SQLite events; it is simple and works, but it is not a high-throughput design.
- The frontend assumes the backend is reachable on the local default port unless reconfigured.

## What To Read First Before Big Changes

If you are about to change behavior, read these first:

1. `README.md`
2. `.claude/settings.json`
3. the relevant package under `src/`
4. the matching tests under `tests/`
5. `wiggly-leaping-lerdorf.md` if the change is about planned scope

## Git Context

The branch `claudescientist` has already been pushed to:

- `https://github.com/whenpoem/aiscientist.git`

Do not assume a PR exists unless you verify it.
