# ClaudeScientist

ClaudeScientist is a research-agent augmentation layer for Claude Code. It adds:

- persistent SQLite-backed memory for hypotheses, failures, Elo judgements, and compressed literature notes
- a verification MCP for leakage checks, provenance tracking, pinned metrics, seed perturbation, fairness checks, and held-out budget enforcement
- Claude hooks for interventions, guardrails, and result logging
- a Textual cockpit TUI for monitoring and steering the research state

This repository currently targets the plan labeled `v0.2`. It is suitable for local development and integration work, but it should not be described as production-ready without a fresh end-to-end validation pass.

## Architecture

- `.claude/settings.json`: Claude Code MCP and hook wiring
- `.claude/agents/`: subagent prompts and tool whitelists
- `.claude/hooks/`: intervention, leakage, provenance, and stop hooks
- `.claude/skills/`: SOPs including `research-sop`, `writeup-sop`, and `elo-select`
- `src/memory_mcp/`: SQLite-backed memory MCP
- `src/verify_mcp/`: verification MCP
- `src/cockpit/`: Textual cockpit TUI plus cockpit MCP bridge
- `tests/`: pytest coverage for memory, verify, hooks, cockpit, and end-to-end smoke tests

## Quick Start

Install Python dependencies from the repo root:

```powershell
uv sync
```

Run the cockpit TUI in one terminal:

```powershell
uv run python -m cockpit.tui
```

Claude Code uses the checked-in `.claude/settings.json` to launch the MCP servers. The verify and cockpit MCP transports are stdio.

## Runtime Layout

Default local state:

- shared runtime DB: `.research-agent/state.db`
- held-out datasets: `%USERPROFILE%\.research-agent\heldout\`

Key local workflows:

```powershell
uv run python -m memory_mcp.dev_server
uv run python -m verify_mcp.dev_server
uv run python -m cockpit.mcp_server
uv run python -m claudescientist.heldout register <name> <path>
```

## Validation

Typical checks:

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/hooks tests/cockpit tests/e2e
uv run python -c "import memory_mcp.server; import verify_mcp.server; import cockpit.mcp_server; print('OK')"
```

## Current Scope Limits

- The exposed verify tools now include `leakage_check`, `record_provenance`, `check_provenance`, `pin_metric`, `seed_perturb`, `baseline_fairness`, and `query_heldout`.
- The prover agent is still a placeholder; Lean MCP is not wired in this repo.
- `snapshot` persists graph state, but the cockpit focuses on the live state rather than historical snapshot browsing.
- The cockpit is terminal-first in v0.2. There is no supported browser UI, no Vite frontend, and no `uvicorn` process to run.
