# ClaudeScientist

> 中文版本: [README.zh-CN.md](README.zh-CN.md)

ClaudeScientist is a research-agent augmentation layer for Claude Code. It does not replace Claude Code's runtime — it adds the layer that AI scientist systems consistently leave out: persistent memory, verifiable experiment results, an interruptible research loop, and a real-time human-in-the-loop dashboard.

The repository currently ships the **v3.0** plan: a continuously-running, budgeted Bradley-Terry tournament with honest 95% confidence intervals, refreshable provenance DAGs, and preregistration with multiple-comparison correction.

**v4.0.0a0 (alpha) is shipped**: ClaudeScientist is now a **two-trunk architecture** — the existing ML reproducibility surface is the *empirical trunk*, and a new *proof trunk* (`prove_mcp`) handles statistical proof generation with optional Lean reinsurance. Both trunks share one core: hypothesis graph, failure ledger, BT tournament, calibration, replay, cockpit. Cold-start data ships in `data/`; Lean is opt-in (see [`docs/setup-lean.md`](docs/setup-lean.md)). See [ADR 0008](docs/adr/0008-two-trunk-domain-architecture.md) and [architecture.md §13](docs/architecture.md#13-core-vs-domain-trunks-v40).

## Five-minute orientation

If you are new to the project, read in this order:

1. **[`docs/overview.md`](docs/overview.md)** — the complete mental model
2. **[`docs/workflows/first-research-task.md`](docs/workflows/first-research-task.md)** — a concrete walkthrough of one task
3. **[`docs/architecture.md`](docs/architecture.md)** — the cross-module contracts
4. **[`docs/tool-reference.md`](docs/tool-reference.md)** — the full MCP tool catalog

For the distilled rationale of each major decision: **[`docs/adr/`](docs/adr/)**.

Looking ahead: **[`docs/roadmap.md`](docs/roadmap.md)** lays out the post-v3.0 directions.

Historical design decisions live in **[`docs/archive/`](docs/archive/)**.

## What is in the box

- **Memory MCP** — hypothesis graph (with proof-trunk node kinds), Bradley-Terry ranking (cross-kind for hypothesis + proof_skeleton), calibration ledger, replay branches (proof-aware snapshot), failure ledger (cross-domain), compressed literature notes
- **Verify MCP** — leakage detection, refreshable provenance DAG, pinned metrics, seed perturbation, baseline fairness, sequestered-dataset budget enforcement, preregistration with BH/Bonferroni correction, resource ledger
- **Prove MCP** *(v4.0)* — proof corpus + bidirectional max-matching retrieval, NL workflow (segment → diagnose → correct), Lean reinsurance interface (triage + attempt log)
- **Hooks** — PreToolUse leakage and destructive-command guards, PostToolUse provenance logger, intervention pump, proof-aware stop flush
- **Cockpit TUI** — terminal-first monitoring and steering surface, with English/Chinese label switching, a live Bradley-Terry leaderboard, and proof-trunk events
- **Cold-start data** — `data/proof_corpus_seed.jsonl` (≥80 statistical proof problems) + `data/proof_failure_seed.jsonl` (≥60 common proof failure modes), loaded by `scripts/seed_proof_corpus.py` / `scripts/seed_proof_failures.py`

## Quick start

Install dependencies from the repository root:

```powershell
uv sync                  # ML/empirical trunk only
uv sync --extra proof    # also installs sentence-transformers for the proof trunk
```

After `uv sync --extra proof`, seed the proof corpus once:

```powershell
uv run python scripts/seed_proof_corpus.py
uv run python scripts/seed_proof_failures.py
```

The default embedding backend is `local` (sentence-transformers/all-MiniLM-L6-v2). Override with `RESEARCH_AGENT_EMBED_BACKEND=mock|openai`. Tests pin `mock` automatically.

Lean reinsurance is **opt-in**. To enable, follow [`docs/setup-lean.md`](docs/setup-lean.md) (one-time elan + mathlib + lean-lsp-mcp install).

For normal local use, open two terminals from the repository root.

**Terminal A** runs Claude Code, which will use `.claude/settings.json` to launch the memory, verify, cockpit, arxiv, and openalex MCP servers:

```powershell
cd D:\aiscientist\claudescientist
claude
```

**Terminal B** runs the cockpit TUI:

```powershell
cd D:\aiscientist\claudescientist
uv run python -m cockpit.tui
```

For the Chinese UI on Windows Terminal:

```powershell
cd D:\aiscientist\claudescientist
chcp 65001
$env:PYTHONUTF8=1
uv run python -m cockpit.tui --lang zh
```

Inside the TUI, press `L` to toggle English / Chinese labels.

## Runtime layout

Default local state:

- shared runtime DB at `.research-agent/state.db` under the repository root
- sequestered dataset directory under `%USERPROFILE%`, configurable via `RESEARCH_AGENT_HELDOUT_DIR`

Useful commands:

```powershell
uv run python -m memory_mcp.dev_server
uv run python -m verify_mcp.dev_server
uv run python -m prove_mcp.dev_server
uv run python -m cockpit.mcp_server
uv run python -m claudescientist.heldout register <name> <path>
```

## Validation

Typical checks before shipping a change:

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/prove_mcp tests/hooks tests/cockpit tests/scripts tests/e2e
uv run python -m cockpit.tui --once --lang zh
uv run python -c "import memory_mcp.server; import verify_mcp.server; import prove_mcp.server; import cockpit.mcp_server; print('OK')"
```

## Status and scope limits

This repository is suitable for local development and integration work, but it should not be described as production-ready without a fresh end-to-end validation pass.

- **Auto-prune is dry-run by default.** Set `RESEARCH_AGENT_AUTO_PRUNE=1` to let `suggest_pause_low_strength` actually flip `mem_bt_ratings.status` to `paused`.
- **The cockpit is terminal-first.** There is no supported browser frontend, no Vite, and no `uvicorn` process to run.
- **The prover agent is activated** in v4.0.0a0 with `mcp__lean__*` tools whitelisted, but the `lean` MCP server entry stays disabled (`_lean`) until the user runs `docs/setup-lean.md`. Without that, the prover agent reports `lean MCP not configured` and bails cleanly — the NL proof workflow remains fully usable without Lean.
- **`mem_nodes.elo_score` is preserved** as a backwards-compatibility column. New code should read `mem_bt_ratings.strength` and friends.

For the complete tool list and all known scope limits, see [`docs/tool-reference.md`](docs/tool-reference.md) and [`AGENTS.md`](AGENTS.md).
