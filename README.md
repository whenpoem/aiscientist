# ClaudeScientist

**Research memory, result verification, and a local monitoring interface for Claude Code and Codex.**

[![version](https://img.shields.io/badge/version-v5.1.4-blue)](https://github.com/whenpoem/aiscientist/releases) [![python](https://img.shields.io/badge/python-%E2%89%A53.11-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![CI](https://github.com/whenpoem/aiscientist/actions/workflows/ci.yml/badge.svg)](https://github.com/whenpoem/aiscientist/actions/workflows/ci.yml) [![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

> 中文版本: [README.zh-CN.md](README.zh-CN.md)

ClaudeScientist adds persistent research records, result checks, statistical
proof tools, and a terminal monitoring interface to Claude Code and Codex.
It stores hypotheses, evidence, comparisons, experiment records, and user
interventions in a local SQLite database inside each research project.

The agent can use these records to compare hypotheses, run checked experiments,
and verify reported results. A second terminal can display the current research
state and accept user decisions while the agent is working.

**Current version**: v5.1.4 separates public installation, per-workspace
configuration, and source development. It adds `claudescientist configure`,
loads `.research-agent/config.toml` automatically, packages Lean as a disabled
optional MCP, and keeps the older project wizard under `dev-setup` for source
contributors. It retains the v5.1 trust-calibration and portability changes.
Bradley-Terry rankings are refit from the complete ledger and no longer depend
on comparison order; their intervals are honestly labelled as uncalibrated
approximations. Bonferroni families are fixed when locked. Every central run
automatically fingerprints code, inputs, Git state, dependencies, seeds, and
runtime. A public Codex plugin bundles the core MCPs, Skills, hooks, and local
Cockpit without tying them to this repository's working directory. The v5.0
activity-streaming Cockpit remains intact; see
[ADR 0011](docs/adr/0011-cockpit-activity-streaming.md).

**v4.2.0 features retained** (see [retrospective-v4.2.md](docs/retrospective-v4.2.md)): tab grouping into Cross / Empirical / Proof, collapsible detail sections, pane-scoped `w`/`i`/`t` keys, the multi-provider vector backend (DashScope / Jina / Voyage / GLM tested via [ADR 0010](docs/adr/0010-multi-provider-embeddings.md), default local `Qwen/Qwen3-Embedding-0.6B`), reports-as-files (closure / draft / diagnostic / portfolio / cascade) per [ADR 0009](docs/adr/0009-reports-as-files-monitoring-as-tui.md), and the cold-start Welcome screen. See [architecture.md §13](docs/architecture.md#13-core-vs-domain-trunks-v40) for the two-trunk split.

## What it looks like

Open one terminal for Codex or Claude Code and a second terminal for Cockpit.

<picture>
  <img alt="Cockpit TUI screenshot" src="docs/assets/image2.png" width="800">
</picture>

*The cockpit TUI — hypothesis tree, evidence, ratings, and event stream in one terminal.*

The two terminals do not communicate directly. They both read and write the same
SQLite file. The modules therefore share local state through a database file,
not through a network service.

| Role | Where | What it does |
|---|---|---|
| **Claude Code / Codex** | Terminal A | Reads your question, calls tools, and writes and runs code |
| **MCP servers** | Background | Provide the tools the agent calls — memory, verification, literature search, proof generation |
| **Hooks** | Auto-loaded at startup | Run safety checks before/after every tool call (block data leaks, log provenance) |
| **Cockpit TUI** | Terminal B | Shows live state; lets you approve, reject, or redirect hypotheses |
| **SQLite** | `.research-agent/state.db` | The single file that holds all state: hypotheses, evidence, ratings, metrics, events |

## What you can do with it

- **Store research decisions.** Every hypothesis, piece of evidence, and branch decision is saved in a persistent graph. Ingested papers are searchable. Counterfactual replay can examine an earlier decision without changing the active graph.
- **Rank competing ideas.** Bradley-Terry comparisons produce
  head-to-head and produces an order-invariant leaderboard with explicitly
  uncalibrated approximate posterior intervals. Use it with comparison coverage
  and domain evidence, not as a significance test.
- **Set confirmatory criteria before experimenting.** Preregistration records the metric, direction, and threshold before results are observed. Multiple-comparison correction is applied automatically.
- **Make your numbers trustworthy.** Every reported number gets checked: Is it reproducible across random seeds? Which files produced it? Has anything changed since? Baseline comparisons are checked for fair compute budgets. A reviewer agent blocks any unverified claim from reaching a writeup.
- **Reuse debugging records.** The failure ledger stores previous problems and their solutions. Similar records can be retrieved during later debugging.
- **Monitor and intervene.** Cockpit shows the hypothesis tree, ratings, and event stream. You can reject a hypothesis or add a note; Codex receives the intervention at the next supported hook event.
- **Generate and verify statistical proofs** *(v4.0).* A proof trunk handles drafting, segmentation, diagnosis against known error patterns, and optional Lean 4 formal verification.

## Quick start

### Install for Codex

The recommended installation keeps the `claudescientist` command available and
then installs the matching Codex plugin. Install `uv` and Codex first, and check
that both commands are available:

```powershell
uv --version
codex --version
```

Install the Python package and the public plugin:

```powershell
uv tool install claudescientist==5.1.4
claudescientist setup --scope user
```

The first command installs the CLI, MCP backends, Doctor, and Cockpit. The
second command installs the Codex plugin from the matching GitHub `v5.1.4` tag.
The plugin contains Skills, hooks, and MCP configuration. Codex can then use the
same installation from any research project; it does not need to start inside
this source checkout.

Open a terminal in each research project and configure that workspace once:

```powershell
cd D:\path\to\your-research-project
claudescientist configure --workspace .
claudescientist doctor --workspace .
```

The configuration command writes non-secret project settings to
`.research-agent/config.toml`. It covers the embedding backend, held-out data
directory, auto-prune, and the optional Lean project path. ClaudeScientist
loads this file automatically; ordinary plugin users do not need a project
`.env` file.

Start a new Codex task after installation or configuration. Approve/trust the
plugin hooks when Codex asks. MCP monitoring works without hook trust, but
Cockpit interventions remain **monitor-only** until the hooks are trusted.

Start Codex in that project. In a second terminal, open Cockpit with the same
workspace path:

```powershell
codex -C .

# Run this in the second terminal
claudescientist cockpit --workspace .
```

Use `$research-sop <question>` in Codex to start the full research workflow, or
choose a Skill from `/skills`. Each project keeps independent state in
`.research-agent/state.db`.

The plugin enables the four local core MCPs (`memory`, `verify`, `prove`,
`cockpit`) by default. It also bundles version-pinned arXiv, OpenAlex, and Lean
MCP definitions in the disabled state. Enable them in Codex only when needed.
Lean also requires a local toolchain and mathlib project. See the detailed
[Codex installation and use guide](docs/setup-codex-plugin.md) and
[Lean setup guide](docs/setup-lean.md).

Do not run `claudescientist dev-setup` for an ordinary plugin installation.
`setup --scope project` remains only as a deprecated compatibility alias.

### Develop from this checkout

Install and run the setup wizard:

```powershell
uv sync
uv run claudescientist dev-setup
```

The wizard walks you through AI client selection (`claude`, `codex`, or
`both`), embedding backend, proof corpus seeding, held-out directory, Lean
toolchain, and auto-prune — all in one pass. Run it again any time; it skips
steps that are already done.

For non-interactive setup, set `CLAUDESCIENTIST_SETUP_AGENT_HOST=codex` or
`CLAUDESCIENTIST_SETUP_AGENT_HOST=both`. Codex support is project-local: setup
generates `.codex/config.toml`, `.codex/agents/*.toml`, and repo skills under
`.agents/skills/` from the existing Claude Code assets.

Literature search uses two external MCPs. arXiv is launched through
`uv tool run arxiv-mcp-server==0.5.0`; OpenAlex is launched through
`npx -y openalex-research-mcp@0.5.0`, so install Node.js/npm if you want the
OpenAlex-backed librarian tools. The current development plugin carries both
definitions but keeps them disabled until selected; see
[docs/setup-codex-plugin.md](docs/setup-codex-plugin.md).

<details><summary>Manual setup (without the wizard)</summary>

```powershell
uv sync --extra proof    # pulls in sentence-transformers for the proof trunk
uv run python scripts/seed_proof_corpus.py
uv run python scripts/seed_proof_failures.py
```

</details>

For checkout development, open two terminals from the repo root:

```powershell
# Terminal A: Claude Code (from the repo root)
claude

# Or Terminal A: Codex (after choosing codex/both in setup)
codex -C .

# Terminal B: cockpit TUI (from the repo root)
uv run python -m cockpit.tui
```

For the Chinese UI on Windows Terminal:

```powershell
chcp 65001
$env:PYTHONUTF8=1
uv run python -m cockpit.tui --lang zh
```

Press `L` inside the TUI to toggle English / Chinese labels.

In Codex, start ClaudeScientist skills with `/skills` or `$skill-name`.
Example:

```text
$research-sop investigate whether per-head dropout helps ViT scaling
```

In Codex, do not type `/research-sop`; that form is for Claude Code.
If `$research-sop` does not appear in project-local development mode, check that
`.agents/skills/research-sop/SKILL.md` exists and restart Codex. Installed plugin
skills work from any project directory.

Lean formal verification is a separate opt-in setup. In Codex, the generated
Lean MCP server is disabled until you finish that setup. See
[`docs/setup-lean.md`](docs/setup-lean.md).

## Where to go next

If you're new, read in this order:

1. **[`docs/overview.md`](docs/overview.md)** — how the components work together and how a task is recorded
2. **[`docs/workflows/first-research-task.md`](docs/workflows/first-research-task.md)** — walk through one full task from start to finish
3. **[`docs/architecture.md`](docs/architecture.md)** — the contracts between modules (treat as binding)
4. **[`docs/tool-reference.md`](docs/tool-reference.md)** — every MCP tool, with signature and usage guidance
5. **[`docs/setup-codex-plugin.md`](docs/setup-codex-plugin.md)** — portable Codex installation and Cockpit trust checks

More:

- Design rationale for each major decision → [`docs/adr/`](docs/adr/)
- Where the project is headed → [`docs/roadmap.md`](docs/roadmap.md)
- Historical plans → [`docs/archive/`](docs/archive/)
- Agent and contributor rules → [`AGENTS.md`](AGENTS.md)

## Runtime details

Default paths:

- Shared state: `.research-agent/state.db` under the active research workspace
- Generated reports: `reports/` under the active research workspace; gitignored by default,
  force-add individual files only when you intentionally want to share them
- Held-out datasets: `%USERPROFILE%\.research-agent\heldout`, configurable via `RESEARCH_AGENT_HELDOUT_DIR`
- Embedding backend: `local` (sentence-transformers/Qwen/Qwen3-Embedding-0.6B); override with `RESEARCH_AGENT_EMBED_BACKEND=mock|openai`. Tests use `mock` automatically.

Dev server commands for individual MCP modules:

```powershell
uv run python -m memory_mcp.dev_server
uv run python -m verify_mcp.dev_server
uv run python -m prove_mcp.dev_server
uv run python -m cockpit.mcp_server
uv run python -m claudescientist.heldout register <name> <path>
```

## Validation

Before shipping a change:

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/prove_mcp tests/hooks tests/cockpit tests/scripts tests/e2e
uv run python -m cockpit.tui --once --lang zh
uv run python -c "import memory_mcp.server; import verify_mcp.server; import prove_mcp.server; import cockpit.mcp_server; print('OK')"
```

## Current status

The repo works for local development and integration. A fresh end-to-end validation pass is needed before calling it production-ready.

A few things to know:

- **Auto-prune is dry-run by default.** Set `RESEARCH_AGENT_AUTO_PRUNE=1` to let it actually pause weak branches.
- **The cockpit is terminal-only.** No browser frontend, no web server.
- **The prover agent works without Lean.** The natural-language proof workflow runs on its own; Lean is an optional formal-verification tool that can be configured later through [`docs/setup-lean.md`](docs/setup-lean.md).
- **`mem_nodes.elo_score` is a legacy column.** New code should read `mem_bt_ratings.strength`.

Protection labels are deliberately explicit: `enforced` means code blocks the
normal operation; `agent_gated` means the agent workflow refuses or reviews it
but is not a security boundary; `advisory` means warning only. Run
`claudescientist doctor --workspace .` to see whether Cockpit intervention hooks
are trusted or the current session has degraded to monitor-only mode.

Full tool list and scope details: [`docs/tool-reference.md`](docs/tool-reference.md) and [`AGENTS.md`](AGENTS.md).
