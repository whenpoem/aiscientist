# ClaudeScientist

ClaudeScientist is a research-agent augmentation layer for Claude Code. It adds:

- persistent SQLite-backed memory for hypotheses, failures, Bradley-Terry judgements, calibration, and compressed literature notes
- a verification MCP for leakage, provenance, pinned metrics, seed perturbation, fairness, held-out budget, **preregistration with BH/Bonferroni correction, refresh-able provenance DAG, and a resource budget ledger**
- Claude hooks for interventions, guardrails, and result logging
- a Textual cockpit TUI for monitoring and steering the research state, with realtime Bradley-Terry leaderboards and counterfactual replay

This repository currently targets the plan labeled `v3.0`. v3.0 builds on v0.2 by turning the research pipeline into a continuously-running, budgeted Bradley-Terry tournament with honest 95% intervals; see [docs/plan-v3.0.md](docs/plan-v3.0.md). It is suitable for local development and integration work, but it should not be described as production-ready without a fresh end-to-end validation pass.

## Architecture

- `.claude/settings.json`: Claude Code MCP and hook wiring
- `.claude/agents/`: subagent prompts and tool whitelists
- `.claude/hooks/`: intervention, leakage, provenance, and stop hooks
- `.claude/skills/`: SOPs including `research-sop`, `writeup-sop`, and `elo-select`
- `src/memory_mcp/`: SQLite-backed memory MCP
- `src/verify_mcp/`: verification MCP
- `src/cockpit/`: Textual cockpit TUI plus cockpit MCP bridge
- `tests/`: pytest coverage for memory, verify, hooks, cockpit, and end-to-end smoke tests

For cross-module contracts that later agents should preserve, see
`docs/design-contracts.md`.

## Quick Start

Install Python dependencies from the repo root:

```powershell
uv sync
```

For normal local use, open two terminals from the repo root.

Terminal A runs Claude Code. Claude Code will use `.claude/settings.json` to
launch the memory, verify, cockpit, arxiv, and openalex MCP servers:

```powershell
cd D:\aiscientist\claudescientist
claude
```

Terminal B runs the cockpit TUI:

```powershell
cd D:\aiscientist\claudescientist
uv run python -m cockpit.tui
```

Chinese UI on Windows Terminal:

```powershell
cd D:\aiscientist\claudescientist
chcp 65001
$env:PYTHONUTF8=1
uv run python -m cockpit.tui --lang zh
```

Inside the TUI, press `L` to toggle English / Chinese UI labels. If Chinese
renders as mojibake in PowerShell, rerun the `chcp 65001` and
`$env:PYTHONUTF8=1` commands before starting the TUI.

The verify and cockpit MCP transports are stdio. There is no browser frontend
to start.

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
uv run python -m cockpit.tui --once --lang zh
uv run python -c "import memory_mcp.server; import verify_mcp.server; import cockpit.mcp_server; print('OK')"
```

## Current Scope Limits

- v3.0 verify tools: `leakage_check`, `record_provenance`, `check_provenance`, `pin_metric`, `seed_perturb`, `baseline_fairness`, `query_heldout`, `refresh_claim`, `preregister`, `resolve_preregistration`, `list_preregistrations`, `budget_check`, `budget_consume`.
- v3.0 memory tools add: `update_bt_rating`, `get_bt_leaderboard`, `suggest_pause_low_strength`, `resume_branch`, `expected_information_gain`, `record_calibration`, `calibration_report`, `replay_counterfactual`, `list_replay_branches`.
- Realtime pruning is **dry-run by default**. Set `RESEARCH_AGENT_AUTO_PRUNE=1` to let `suggest_pause_low_strength` actually flip `mem_bt_ratings.status` to `paused`.
- The prover agent is still a placeholder; Lean MCP is not wired in this repo.
- `snapshot` persists graph state, but the cockpit focuses on the live state rather than historical snapshot browsing.
- The cockpit is terminal-first. There is no supported browser UI, no Vite frontend, and no `uvicorn` process to run.
