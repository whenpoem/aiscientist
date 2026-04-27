# AGENTS.md

This file is for any later LLM or coding agent working in this repository.

## What This Repo Is

`claudescientist` is a Research-Agent augmentation layer for Claude Code.

It currently provides:

- persistent SQLite-backed memory
- verification tools for leakage, provenance, pinned metrics, seed perturbation, baseline fairness, and held-out budget checks
- Claude hooks for intervention and safety checks
- a Textual cockpit TUI with English / Chinese UI switching
- a stdio FastMCP cockpit bridge

This repo is usable for local development and integration work.
Do **not** describe it as "production-ready" without doing a fresh end-to-end check.

## Scope Reality

The implementation in this repo has shipped the `v3.0` plan ([docs/plan-v3.0.md](docs/plan-v3.0.md)).
Do not casually rename that to "V1.0 complete" or "production-ready" unless you have verified the remaining product and operations expectations yourself.

Known scope limits to remember:

- v3.0 verify tools: `leakage_check`, `record_provenance`, `check_provenance`, `pin_metric`, `seed_perturb`, `baseline_fairness`, `query_heldout`, `refresh_claim`, `preregister`, `resolve_preregistration`, `list_preregistrations`, `budget_check`, `budget_consume`.
- v3.0 memory tools add: `update_bt_rating`, `get_bt_leaderboard`, `suggest_pause_low_strength`, `resume_branch`, `expected_information_gain`, `record_calibration`, `calibration_report`, `replay_counterfactual`, `list_replay_branches`.
- Auto-prune is opt-in via `RESEARCH_AGENT_AUTO_PRUNE=1`. Default is dry-run (only emits `branch_pause_suggested`).
- The prover agent is still a stub. Lean MCP tools are not wired in this repo yet.
- `mem_nodes.elo_score` is preserved as a backwards-compatibility column; new code should read `mem_bt_ratings.strength` and friends.
- `snapshot` persists memory state, but cockpit still focuses on live state rather than first-class historical snapshot browsing.
- The cockpit has English and Chinese labels (`--lang en|zh`, or press `L` inside the TUI), but it is still terminal-first; there is no supported browser frontend.

## Important Paths

- Claude config: `.claude/settings.json`
- Claude agents: `.claude/agents/`
- Claude skills: `.claude/skills/`
- Claude hooks: `.claude/hooks/`
- memory MCP: `src/memory_mcp/`
- verify MCP: `src/verify_mcp/`
- cockpit TUI + MCP bridge: `src/cockpit/`
- held-out dataset CLI: `src/claudescientist/heldout.py` and `src/claudescientist/heldout_cli.py`
- cockpit UI text: `src/cockpit/i18n.py`
- cross-module contracts: `docs/design-contracts.md`
- tests: `tests/`
- project plans: `wiggly-leaping-lerdorf.md`, `docs/plan-v0.2.md`

## How Things Actually Run

### Python side

This repo uses `uv` and Python 3.11.

Common commands:

```powershell
uv run pytest tests/memory_mcp tests/verify_mcp tests/hooks tests/cockpit tests/e2e
uv run ruff check
uv run python -m cockpit.tui
uv run python -m cockpit.tui --lang zh
uv run python -m cockpit.mcp_server
```

On Windows, use UTF-8 before launching the Chinese TUI:

```powershell
chcp 65001
$env:PYTHONUTF8=1
uv run python -m cockpit.tui --lang zh
```

## MCP and Tooling Notes

The Claude settings are already wired for these MCP servers:

- `memory`
- `verify`
- `cockpit`
- `arxiv`
- `openalex`

Important detail:

- `openalex-research-mcp` is configured through `npx -y openalex-research-mcp`, not `uv`, because the real package is a Node CLI in this environment.
- The cockpit MCP runs over stdio through `uv run python -m cockpit.mcp_server`.
- The cockpit UI is terminal-first in v0.2. There is no supported browser frontend in this repo.

If you change `.claude/settings.json`, assume Claude Code may need a fresh session to reload MCP and hooks.

## Database and State Notes

Shared runtime state is stored in:

- `.research-agent/state.db` by default, or `RESEARCH_AGENT_DB_PATH` when explicitly overridden
- held-out datasets live under `%USERPROFILE%\.research-agent\heldout\` by default, or `RESEARCH_AGENT_HELDOUT_DIR` when explicitly overridden

This state is used by:

- memory MCP
- verify MCP provenance storage
- cockpit event/intervention flow
- hooks such as `intervention_pump.py`
- held-out dataset registration and budget counters

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
uv run pytest tests/memory_mcp tests/verify_mcp tests/hooks tests/cockpit tests/e2e
```

If cockpit code changed, also smoke-test the TUI entrypoint:

```powershell
uv run python -m cockpit.tui --once
uv run python -m cockpit.tui --once --lang zh
```

If integration points changed, also smoke-test the backend:

```powershell
uv run python -c "import memory_mcp.server; import verify_mcp.server; import cockpit.mcp_server; print('OK')"
```

## Known Fragile Areas

- Hook behavior depends on the shared state DB and stop-flush state file under `.research-agent/`; if those files are missing or malformed, some protections degrade to permissive or fallback behavior.
- The cockpit live view still uses polling against SQLite events; it is simple and works, but it is not a high-throughput design.
- Held-out dataset protection depends on shared root resolution (`RESEARCH_AGENT_HELDOUT_DIR`), registered `ver_heldout_budgets.heldout_path` rows, pointer files, and `leakage_guard.py`. Do not bypass this path by reading held-out files directly; use `query_heldout`.
- Cockpit UI labels should go through `src/cockpit/i18n.py` so English and Chinese modes stay aligned.

## What To Read First Before Big Changes

If you are about to change behavior, read these first:

1. `README.md`
2. `docs/design-contracts.md`
3. `.claude/settings.json`
4. the relevant package under `src/`
5. the matching tests under `tests/`
6. `wiggly-leaping-lerdorf.md` if the change is about planned scope

## Git Context

The branch `claudescientist` has already been pushed to:

- `https://github.com/whenpoem/aiscientist.git`

Do not assume a PR exists unless you verify it.
