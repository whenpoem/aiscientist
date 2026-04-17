# ClaudeScientist

ClaudeScientist is a research-agent augmentation layer for Claude Code. It adds:

- persistent SQLite-backed memory for hypotheses, failures, and compressed literature notes
- a verification MCP for leakage checks, provenance tracking, and pinned metrics
- Claude hooks for intervention, guardrails, and result logging
- a cockpit backend and React frontend for monitoring the research state

This repository currently matches the plan labeled `v0.1 / Phase 0-6`. It is suitable for local development and integration work, but it should not be described as production-ready without a fresh end-to-end validation pass.

## Architecture

- `.claude/settings.json`: Claude Code MCP and hook wiring
- `.claude/agents/`: subagent prompts and tool whitelists
- `src/memory_mcp/`: SQLite-backed memory MCP
- `src/verify_mcp/`: verification MCP
- `src/cockpit/`: FastAPI backend and MCP mount
- `src/cockpit/frontend/`: Vite/React cockpit UI
- `tests/`: pytest coverage for memory, verify, hooks, and a cockpit smoke test

## Quick Start

Install Python dependencies from the repo root:

```powershell
uv sync
```

Run the backend:

```powershell
uv run uvicorn cockpit.server:app --port 7777
```

Run the frontend from `src/cockpit/frontend`:

```powershell
npm ci
npm run dev
```

Use the checked-in `package-lock.json` as the source of truth. The frontend stack is on very new 2026-era versions, so prefer `npm ci` over a fresh unlocked install.

Default local endpoints:

- cockpit backend: `http://127.0.0.1:7777`
- cockpit MCP mount: `http://127.0.0.1:7777/mcp`
- cockpit frontend: `http://localhost:5173`

## MCP Notes

The configured MCP servers are:

- `memory`: local Python server via `uv run python -m memory_mcp.dev_server`
- `verify`: local Python server via `uv run python -m verify_mcp.dev_server`
- `cockpit`: HTTP MCP mounted by the FastAPI backend
- `arxiv`: upstream `arxiv-mcp-server` launched via `uv tool run`
- `openalex`: upstream `openalex-research-mcp` launched via `npx -y openalex-research-mcp`

Important detail: `openalex-research-mcp` is a Node/npm package in the current upstream distribution. Do not rewrite it back to a `uv`-managed Python command unless the upstream package changes.

## Validation

Typical checks:

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/hooks tests/e2e
uv run python -c "import memory_mcp.server; import verify_mcp.server; from cockpit.server import app; print('OK')"
```

If the frontend changed:

```powershell
cd src/cockpit/frontend
npm run build
```

## Current Scope Limits

- The verify MCP currently exposes `leakage_check`, `record_provenance`, `check_provenance`, and `pin_metric`.
- The memory MCP now includes `find_contradictions` and `snapshot`, but snapshot history is not yet surfaced in the cockpit UI.
- The prover agent is still a placeholder; Lean MCP is not wired in this repo.
- Shared runtime state lives in `.research-agent/state.db` by default and can be redirected with `RESEARCH_AGENT_DB_PATH`.
