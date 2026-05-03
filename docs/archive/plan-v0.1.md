# Plan: Research-Agent Augmentation Layer on Claude Code

> **Status**: detailed executable plan, v0.1 scope = Phases 0–6 (scaffold through literature compression).
> **Target machine**: Windows 11, project at `D:\aiscientist\claudescientist` (currently empty).
> **Principle**: Claude Code stays untouched. All contributions are MCP servers, hooks, skills, and subagent templates plugged in around it.
>
> **Locked decisions** (see section 9 for details):
> - **Python env**: `uv`
> - **v0.1 scope**: Phases 0–6, ~15–18 working days
> - **Literature MCPs**: install `arxiv-mcp-server` and `openalex-research-mcp` as-is; our memory-mcp wraps them with a thin `ingest_paper` compression layer
> - **Cockpit-MCP transport**: HTTP on `http://localhost:7777/mcp` (fastmcp sub-app mounted inside the same uvicorn process as the REST/WS cockpit)

---

## 1. Context

We're building a "脑外挂 (brain prosthesis)" for research automation in statistics / DS / AI, layered on top of Claude Code. The motivation is unchanged from the original brief:

- Existing AI-Scientist systems (EvoScientist, AI Scientist v2, AI-Researcher, InternAgent) spend 40–60% of their code on agent-runtime plumbing that Claude Code already gives us for free.
- Their "persistent memory" is just vector cosine similarity — no append-only, no contradictions, no time.
- Their "verification" is "did the code run" — no reward-hacking check, no leakage, no provenance.

Our bet: build only the layer that's genuinely missing (memory, verification, cockpit UI), cost nothing on runtime, and keep every piece independently shippable / publishable.

The deliverable is a system a single researcher (you, on Windows 11) can use daily on real research tasks, with a clear upgrade path toward a published comparison against EvoScientist.

---

## 2. Tech Stack Primer

You said some of these are unfamiliar. Here are 2-minute intros per component, with the *why* and a runnable example.

### 2.1 fastmcp 3.x — Python MCP SDK

**What it is**: MCP (Model Context Protocol) is the wire protocol Claude Code uses to talk to external tool servers. `fastmcp` is a decorator-based Python library that turns normal Python functions into MCP tools. Current version as of 2026-04: **3.2.x**.

**Why it, not the official `mcp` package**: The official `mcp` package (version 1.27) requires you to hand-write JSON schemas for every tool, handle raw request/response envelopes, and manage the stdio server loop yourself. `fastmcp` does all this from Python type hints and docstrings. For a project with ~20 tools across 3 servers, this saves hundreds of lines.

**Minimal example**:

```python
from fastmcp import FastMCP

mcp = FastMCP("memory")

@mcp.tool
def record_failure(trigger: str, symptom: str, resolution: str) -> dict:
    """Record a failure for future signature matching."""
    # your logic here
    return {"failure_id": "f_42", "stored": True}

if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport (what CC wants)
```

**Registration in Claude Code** (`.claude/settings.json`):

```json
{
  "mcpServers": {
    "memory": {
      "command": "uv",
      "args": ["run", "python", "-m", "memory_mcp.dev_server"]
    }
  }
}
```

### 2.2 uv — Python env + script runner

**What it is**: `uv` is a Rust-written Python package manager / venv manager / script runner, written by Astral (same people as `ruff`). Replaces pip + virtualenv + pip-tools + pyenv + pipx in one binary. Installs Python itself too.

**Why it matters for us on Windows**: Claude Code hooks are shell commands. If a hook says `python hooks/pre.py`, we hit the Windows mess — `python` might not be on PATH, `python3` doesn't exist by default, and the project venv isn't automatically activated. With `uv run python hooks/pre.py`, `uv` auto-discovers the project's `pyproject.toml`, resolves the right interpreter, and runs the script — deterministic and cross-platform.

**Install on Windows**:

```powershell
winget install --id=astral-sh.uv -e
```

**Usage pattern**:

```powershell
# in project root
uv init --lib                    # creates pyproject.toml + .python-version
uv add fastmcp fastapi uvicorn   # like pip install, also updates lockfile
uv add --dev pytest ruff
uv run python -m memory_mcp.dev_server   # runs in project env, no activate needed
uv run pytest                    # same
```

The `uv.lock` file pins everything reproducibly.

### 2.3 SQLite + FTS5

**What it is**: SQLite is a single-file embedded database. FTS5 is its built-in full-text search extension (with BM25 ranking). Both ship with Python's `sqlite3` stdlib — zero extra installs.

**Why, vs. Postgres / DuckDB / vector DB**: Single-user, single-project, local-only. We want the state to be `cp`-able. SQLite in WAL mode handles multiple writers (our three MCPs + the cockpit) just fine at this scale.

**Why FTS5, vs. scikit-learn TF-IDF**: FTS5 is already inside SQLite. We want phrase + substring + BM25 ranking over failure-ledger text; FTS5 does all of that with SQL. A scikit-learn TF-IDF pipeline would need its own persistence and retraining — 10× the complexity for no benefit at our scale.

**Minimal schema example**:

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE mem_failures (
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  symptom TEXT NOT NULL,
  root_cause TEXT,
  resolution TEXT,
  first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
  seen_count INTEGER DEFAULT 1
);

CREATE VIRTUAL TABLE mem_failures_fts USING fts5(
  trigger, symptom, root_cause, resolution,
  content='mem_failures', content_rowid='failure_id'
);

CREATE TRIGGER mem_failures_ai AFTER INSERT ON mem_failures BEGIN
  INSERT INTO mem_failures_fts(rowid, trigger, symptom, root_cause, resolution)
  VALUES (new.failure_id, new.trigger, new.symptom, new.root_cause, new.resolution);
END;
```

Query (BM25-ranked, most relevant first):

```sql
SELECT f.* FROM mem_failures f
JOIN mem_failures_fts fts ON fts.rowid = f.failure_id
WHERE mem_failures_fts MATCH ?
ORDER BY bm25(mem_failures_fts) LIMIT 5;
```

### 2.4 FastAPI + WebSocket + uvicorn (cockpit backend)

**What it is**: FastAPI is a modern Python web framework (like Flask, but async-first and auto-generates OpenAPI from type hints). uvicorn is the ASGI server that runs it. WebSocket is the browser↔server bidirectional live-push protocol the cockpit uses.

**Why**: The cockpit needs two channels — REST endpoints for the React frontend to fetch state (`GET /graph`, `GET /claims`) and a WebSocket to push live updates as the research session evolves. FastAPI does both idiomatically in ~50 lines.

**Key pattern we'll use**: fastmcp and FastAPI **can live in the same Python process**. fastmcp's `mcp.http_app()` returns a Starlette/ASGI app that we mount at `/mcp/*` inside uvicorn. Both share one SQLite connection pool. This means the cockpit server is one `uv run uvicorn cockpit.server:app` invocation, not two processes.

### 2.5 Vite + React + @xyflow/react + Tailwind v4 (cockpit frontend)

**What each is**:
- **Vite**: JS/TS bundler + dev server with hot-module-reload. Replaces Create React App (deprecated).
- **React**: UI framework. We'll use the TypeScript template. Version 19.
- **@xyflow/react**: The graph-UI library for React. Was previously called `reactflow`; renamed in 2023. Current: 12.x. Handles pan/zoom/custom-nodes/edges out of the box.
- **Tailwind v4**: Utility-first CSS. v4 (released 2025) dropped the PostCSS config; you install `@tailwindcss/vite` and just `@import "tailwindcss";` in your CSS.

**Why this combo**: It's the most boring stack that produces a production-grade UI. The cockpit is the smallest custom thing and we shouldn't experiment here.

**First-time Windows setup**:

```powershell
# prerequisite: Node.js 20+
winget install OpenJS.NodeJS

cd D:\aiscientist\claudescientist\src\cockpit
pnpm create vite frontend --template react-ts
cd frontend
pnpm install
pnpm add @xyflow/react
pnpm add -D tailwindcss @tailwindcss/vite
pnpm run dev   # opens http://localhost:5173
```

### 2.6 lean-lsp-mcp — third-party Lean MCP

**What it is**: An actively maintained Python MCP wrapper around the Lean 4 LSP. Exposes tools like `lean_goal`, `lean_verify`, `lean_run_code`, `lean_loogle` (type-based premise search), `lean_leansearch` (NL premise search). Repo: `oOo0oOo/lean-lsp-mcp`, MIT licensed, ~300 stars, pinned at a known-good tag.

**Why we use it**: It's the only active Lean MCP. Writing our own is ~2 weeks of work for zero differentiation. We install it as-is.

**Install & register**:

```powershell
# adds lean-lsp-mcp as a uv tool (isolated env)
uv tool install lean-lsp-mcp

# separately: install Lean toolchain
# (elan is Lean's version manager; Windows installer available from elan-lang.org)
```

```json
{
  "mcpServers": {
    "lean": {
      "command": "uv",
      "args": ["tool", "run", "lean-lsp-mcp"]
    }
  }
}
```

---

## 3. Build vs. Buy Matrix

This is the central question you asked — here's the opinionated verdict per component, based on a GitHub ecosystem survey (April 2026):

| Component | Decision | Rationale |
|---|---|---|
| **memory-mcp** | **BUILD** | Anthropic's official `memory` server is TypeScript and stores entities/relations/observations — no append-only semantics, no contradiction detection, no failure-ledger concept, no literature-compression schema. Forking would mean rewriting the core. Build from scratch in Python (~600 LOC estimate). |
| **verify-mcp** | **BUILD** | No ML-specific verification MCP exists on GitHub. SonarQube-MCP exists for general code review but has nothing about data leakage / seed sensitivity / baseline fairness. Build from scratch (~800 LOC estimate). |
| **cockpit** (FastAPI + React) | **BUILD** | Novel component, no equivalent exists. ~400 LOC backend + ~600 LOC frontend. |
| **lean-mcp** | **REUSE AS-IS** | Pin `lean-lsp-mcp` v0.x. Zero development. |
| **Literature ingestion** | **HYBRID** | Install `blazickjp/arxiv-mcp-server` and `oksure/openalex-research-mcp` as separate `mcpServers` (zero dev cost). Our `memory-mcp` adds a thin `ingest_paper` tool that calls them for raw fetch, then runs Claude (via the main model in the subagent) for structured extraction, stores locally. We own only the *compression* layer. |
| **Skills (3 SOPs)** | **BUILD** | Research-specific workflow text. Can't be generic. ~3 × 100-line markdown files. |
| **Subagents (5 roles)** | **BUILD** | Tool whitelists + system prompts. ~5 × 50-line markdown files. |
| **Hooks (PreToolUse, PostToolUse, Stop, UserPromptSubmit)** | **BUILD** | Glue code tied to our schema. ~5 × 80-line Python files. |

**Short version**: we write memory, verify, cockpit, hooks, skills, subagents. We install lean-lsp-mcp, arxiv-mcp, openalex-research-mcp as-is. Nothing else.

---

## 4. Architecture (key decisions)

### 4.1 High-level diagram

```
┌────────────────────────────────────────────────────────────────────┐
│         Research Cockpit — browser at http://localhost:7777         │
│   Hypothesis Graph  │  Verification Dashboard  │  Intervention Btns │
└──────────────────────────────┬─────────────────────────────────────┘
                               │  WebSocket (live push)
                               │  REST (initial state)
┌──────────────────────────────▼─────────────────────────────────────┐
│        cockpit/server.py — ONE uvicorn process                      │
│   FastAPI REST + WS  │  fastmcp sub-app mounted at /mcp             │
└──────────────┬────────────────────────────┬────────────────────────┘
               │                            │ stdio MCP
               │ shared SQLite              │
               ▼                            ▼
┌────────────────────────────┐   ┌────────────────────────────────────┐
│  .research-agent/state.db  │   │   Claude Code (untouched)           │
│  — mem_* tables            │   │  ┌──────────┐  ┌──────────────────┐ │
│  — ver_* tables            │◄──┤  │ 5 sub-   │  │ 3 skills         │ │
│  — cockpit_* tables        │   │  │ agents   │  │ (SOPs)           │ │
│  (WAL mode, FTS5)          │   │  └──────────┘  └──────────────────┘ │
└────────────────────────────┘   │  ┌────────────────────────────────┐ │
               ▲                 │  │ 5 hooks (settings.json)        │ │
               │                 │  └────────────────────────────────┘ │
               │ stdio MCP       └──────┬──────────┬──────────┬────────┘
               │                        │          │          │
┌──────────────┴──────┐   ┌─────────────▼──┐  ┌────▼───────┐  ▼
│  memory-mcp         │   │  verify-mcp    │  │ lean-mcp   │ (arxiv,
│  (our code)         │   │  (our code)    │  │ (3rd party)│  openalex)
└─────────────────────┘   └────────────────┘  └────────────┘
```

### 4.2 Key decision A — State sharing

**Decision**: ONE SQLite file at `.research-agent/state.db`, table-namespaced by prefix (`mem_*`, `ver_*`, `cockpit_*`). WAL mode, foreign keys ON. Every MCP opens its own connection with `isolation_level=None` and uses explicit `BEGIN IMMEDIATE` / `COMMIT`.

**Why not separate files**: The cockpit would need to join across three files to render a node-with-evidence-and-provenance view. A single file gives us free atomicity (hypothesis + its provenance in one transaction) and free referential integrity. WAL mode has never been the bottleneck at our scale.

### 4.3 Key decision B — Intervention queue mechanics

**Decision**: Cockpit writes interventions into `cockpit_interventions` (append-only). Both `UserPromptSubmit` and `Stop` hooks run the same `intervention_pump.py` script that drains undelivered rows and injects them as `additionalContext` into the next turn. Emergency halts (`kind='halt'`) additionally get picked up by the `PreToolUse` hook which exits 2 to block dangerous actions mid-turn.

**Why not a skill or a tool**: A skill requires Claude to remember to call it, which is fragile. A hook is mechanical and mandatory. The `Stop` hook is the earliest point at which an intervention can reach Claude without being rudely interrupted mid-tool-call.

### 4.4 Key decision C — Held-out reservation (Windows-friendly)

**Decision**: Held-out data lives **outside the project tree** at `%USERPROFILE%\.research-agent\held_out\<proj_hash>\<dataset>\`. The project tree contains only a manifest (SHA-256 + schema + row count). Defense-in-depth:

1. **Location isolation**: out-of-tree by default.
2. **PreToolUse leakage hook**: AST-parses every `Write`/`Edit` to `.py` files and pattern-matches every `Bash` command for paths pointing into the held-out directory. Exit 2 to block, unless the env var `RESEARCH_AGENT_VERIFY=1` is set (only verify-mcp sets it).
3. **verify-mcp is the only read path**, with a budget counter in `ver_heldout_budget`.
4. **Manifest hash check** on project open — if held-out files drift from the manifest, hard-lock the whole thing until a human re-confirms.

No reliance on Windows ACLs or chmod 000 (which doesn't exist on Windows).

### 4.5 Key decision D — v0.1 scope

**Decision**: Ship Phases 0–6 (scaffold → subagents+skills → memory-mcp v1 → verify-mcp v1 → hooks wiring → cockpit read-only + reject button → **literature compression**). Estimated 15–18 working days for one developer.

Literature compression was originally slated for v0.2 but is included because: (a) the `librarian` subagent is otherwise dead weight, (b) install-as-is of arxiv-mcp + openalex-mcp makes the incremental cost ~3 days, (c) a research system without literature retrieval isn't usefully testable on real tasks.

Everything else (seed_perturb, baseline_fairness, held-out budget enforcement, prover subagent, multi-project support) lives in v0.2+ and comes *after* you've used v0.1 on a real research task.

### 4.6 Key decision E — Skill vs. subagent vs. hook

| Responsibility | Mechanism | Why |
|---|---|---|
| Block ship-level report writes with unverified claims | **PreToolUse hook** on Write/Edit to `.md` files | Must be mandatory, not advisory |
| Flush hypothesis graph deltas at end of turn | **Stop hook** | Mechanical housekeeping, must not depend on Claude remembering |
| "Run the full research SOP" workflow | **Skill** (`research-sop`) | Multi-step semantic workflow, needs main-thread reasoning context |
| Block destructive bash commands | **PreToolUse hook** on Bash | Policy, not semantics |
| Literature review sub-task in a research session | **Subagent** (`librarian`) | Isolated context, large tool-call budget |

General rule: **hooks for mechanical mandatory, skills for semantic advisory, subagents for isolated sub-problems.**

### 4.7 Key decision F — Dev-mode hot reload

**Problem**: Claude Code spawns MCP servers as child processes at session start and holds them for the whole session. Every code change to our MCPs normally requires restarting CC.

**Decision**: Each MCP server (`memory_mcp`, `verify_mcp`) has two entry points:
- `server.py` — production, imports all logic once at startup
- `dev_server.py` — dev, calls `importlib.reload(impl)` on every tool call, gated by `RESEARCH_AGENT_DEV=1` env var

During development, `.claude/settings.json` points at `dev_server.py`. Edit code → save → call the tool → reloaded. Tool *bodies* hot-swap; tool *signatures* still require a restart. Good enough for 90% of iteration.

---

## 5. Project Layout

```
D:\aiscientist\claudescientist\
├── .claude\
│   ├── settings.json                    # MCP + hook registration
│   ├── agents\
│   │   ├── researcher.md
│   │   ├── engineer.md
│   │   ├── verifier.md
│   │   ├── librarian.md
│   │   └── prover.md                    # stub in v0.1, activated in v0.2
│   ├── skills\
│   │   ├── research-sop\SKILL.md
│   │   ├── debug-sop\SKILL.md
│   │   └── writeup-sop\SKILL.md
│   └── hooks\
│       ├── intervention_pump.py         # Stop + UserPromptSubmit
│       ├── leakage_guard.py             # PreToolUse (Write/Edit/Bash)
│       ├── destructive_bash_guard.py    # PreToolUse (Bash)
│       ├── provenance_log.py            # PostToolUse (Bash/Write)
│       └── stop_flush.py                # Stop (graph deltas)
├── src\
│   ├── memory_mcp\
│   │   ├── __init__.py
│   │   ├── server.py                    # prod entry
│   │   ├── dev_server.py                # dev entry with importlib.reload
│   │   ├── impl.py                      # all tool implementations
│   │   ├── db.py                        # shared connection helper
│   │   └── schema.sql
│   ├── verify_mcp\
│   │   ├── __init__.py
│   │   ├── server.py
│   │   ├── dev_server.py
│   │   ├── impl.py
│   │   ├── leakage.py                   # AST scanner
│   │   ├── provenance.py                # number-token extractor
│   │   └── db.py
│   └── cockpit\
│       ├── server.py                    # FastAPI + WS + fastmcp sub-app
│       ├── db.py                        # shared helper
│       └── frontend\
│           ├── index.html
│           ├── vite.config.ts
│           ├── package.json
│           ├── tailwind.config.js       # (v4 minimal config)
│           └── src\
│               ├── main.tsx
│               ├── App.tsx
│               ├── components\
│               │   ├── HypothesisGraph.tsx    # @xyflow/react
│               │   ├── VerificationTable.tsx
│               │   └── InterventionPanel.tsx
│               ├── hooks\
│               │   └── useWebSocket.ts
│               └── types.ts
├── .research-agent\                     # gitignored runtime state
│   ├── state.db
│   ├── logs\
│   └── sessions\
├── tests\
│   ├── memory_mcp\test_graph.py
│   ├── memory_mcp\test_failures.py
│   ├── verify_mcp\test_leakage.py
│   ├── hooks\test_intervention_pump.py
│   └── e2e\test_smoke.py
├── pyproject.toml                       # uv init
├── uv.lock
├── .python-version                      # 3.11
├── .gitignore
└── README.md
```

---

## 6. v0.1 Executable Plan (Phases 0–6)

Each phase ends with a concrete verification check. Total estimate: **15–18 working days** for one developer.

### Phase 0 — Scaffold & tooling (half day)

**Goal**: empty directory → installable project with Claude Code config that starts without errors.

**Commands (PowerShell)**:

```powershell
# prerequisites (skip if already installed)
winget install --id=astral-sh.uv -e
winget install OpenJS.NodeJS

cd D:\aiscientist\claudescientist

# Python project init
uv init --lib --name claudescientist --python 3.11
uv add fastmcp fastapi "uvicorn[standard]" pydantic
uv add --dev pytest pytest-asyncio ruff

# Directory scaffolding
mkdir -p .claude\agents, .claude\skills, .claude\hooks
mkdir -p src\memory_mcp, src\verify_mcp, src\cockpit\frontend
mkdir -p .research-agent\logs, .research-agent\sessions
mkdir -p tests\memory_mcp, tests\verify_mcp, tests\hooks, tests\e2e
```

**Files to create** (all in this phase):

`.gitignore`:
```
.research-agent/
__pycache__/
*.pyc
.pytest_cache/
node_modules/
dist/
.venv/
```

`.claude/settings.json` (skeleton — hooks & MCPs added later):
```json
{
  "mcpServers": {},
  "hooks": {}
}
```

`README.md`: one paragraph summary.

**Verification**:
```powershell
uv run python -c "import fastmcp; import fastapi; print('OK')"
# should print OK
```

---

### Phase 1 — Subagents & Skills scaffolding (1 day)

**Goal**: 5 subagent templates + 3 skill stubs exist and are invocable from CC.

**Subagent tool whitelists** (remember: no globs — list exact tool names):

#### `.claude/agents/researcher.md`
```markdown
---
name: researcher
description: Read-only literature review, idea generation, and hypothesis proposal. Cannot modify code or files.
tools: Read, Glob, Grep, WebFetch, mcp__memory__get_active_frontier, mcp__memory__get_ancestors, mcp__memory__query_literature, mcp__memory__match_signatures
model: sonnet
---

You are a research assistant focused on idea generation and literature synthesis.

Your job:
1. Read relevant files and prior work.
2. Query the hypothesis graph for current state (`mcp__memory__get_active_frontier`).
3. Propose new hypotheses or refinements, grounded in retrieved literature.
4. NEVER write, edit, or run code. If an idea requires implementation, say so and stop.

Output format: a markdown list of proposed hypotheses with rationale and supporting references.
```

#### `.claude/agents/engineer.md`
```markdown
---
name: engineer
description: Implementation and experimentation. Can write code, run scripts, and record findings to memory.
tools: Read, Write, Edit, Glob, Grep, Bash, mcp__memory__propose_hypothesis, mcp__memory__attach_evidence, mcp__memory__record_failure, mcp__memory__match_signatures, mcp__verify__leakage_check, mcp__verify__record_provenance
model: sonnet
---

You are an ML engineer executing a specific experiment.

Before writing code:
- Call `mcp__memory__match_signatures` with a description of what you're about to do. If a similar past failure exists, read it and change approach.

While implementing:
- Use scikit-learn / PyTorch / NumPy idiomatically.
- Never `fit` a scaler on concatenated train+test.
- Never early-stop on the test split.
- Never hardcode paths into `.research-agent/held_out/`.

After running:
- Call `mcp__verify__record_provenance` with the numeric results.
- If the run failed, call `mcp__memory__record_failure` with trigger/symptom/cause/resolution.
```

#### `.claude/agents/verifier.md`
```markdown
---
name: verifier
description: Independent verification of claims. Read-only access to code; can run verification tools but cannot edit.
tools: Read, Glob, Grep, Bash, mcp__verify__leakage_check, mcp__verify__check_provenance, mcp__verify__seed_perturb, mcp__verify__verify_metric
model: sonnet
---

You are an adversarial verifier. Assume the engineer's claims are wrong until proven otherwise.

For every numeric claim in a report or commit message:
1. Check provenance: `mcp__verify__check_provenance`. Claim without provenance → red flag.
2. Check leakage: `mcp__verify__leakage_check` on the training script.
3. If the claim is central, run `mcp__verify__seed_perturb` to see if it survives.

You CANNOT edit files. If you find a problem, report it and stop — the engineer must fix it.
```

#### `.claude/agents/librarian.md`
```markdown
---
name: librarian
description: Discover and structurally ingest papers from arxiv / openalex. Populates the literature index.
tools: Read, WebFetch, mcp__arxiv__search_papers, mcp__arxiv__get_paper, mcp__openalex__search_works, mcp__openalex__get_citations, mcp__memory__ingest_paper, mcp__memory__query_literature
model: sonnet
---

You discover relevant papers for a research question.

Workflow:
1. Start with `mcp__memory__query_literature` to see what's already ingested.
2. If gaps, query `mcp__arxiv__search_papers` and `mcp__openalex__search_works`.
3. For each relevant paper, call `mcp__memory__ingest_paper` with the arxiv_id or DOI.
4. Return a ranked list of (paper_id, title, relevance-reason).

Never waste budget on papers already in the index.
```

#### `.claude/agents/prover.md` (stub in v0.1)
```markdown
---
name: prover
description: Attempt formal proofs in Lean 4 for stated lemmas. Scope: small statistical identities.
tools: Read, Write, Edit, mcp__lean__lean_goal, mcp__lean__lean_verify, mcp__lean__lean_run_code, mcp__lean__lean_loogle, mcp__lean__lean_leansearch
model: sonnet
---

You are a formal-methods assistant. You take a mathematical lemma written in natural language and attempt to state + prove it in Lean 4 using mathlib.

> NOTE: This subagent is a stub in v0.1. Activated in v0.2 when lean-lsp-mcp is installed.
```

#### Skills (3 SOPs — stub content in v0.1)

`.claude/skills/research-sop/SKILL.md`:
```markdown
---
name: research-sop
description: End-to-end research loop. Use at the start of any new research task — triggers literature review, hypothesis generation, experimentation, verification.
---

# Research SOP

When the user asks a research-shaped question ("investigate X", "does X affect Y", "compare A and B"):

1. **Memory lookup** — call `mcp__memory__match_signatures` with the task description. If prior failures exist, read them first.
2. **Literature gap** — call `mcp__memory__query_literature`. If < 3 relevant papers, spawn the `librarian` subagent.
3. **Hypothesis generation** — spawn the `researcher` subagent with literature context. Ask for 3–5 hypotheses.
4. **Hypothesis selection** — present to user via cockpit (or inline if cockpit not up). Pick one.
5. **Implementation** — spawn the `engineer` subagent.
6. **Verification** — spawn the `verifier` subagent independently.
7. **Write-up** — only if verifier passes.

At every step, call `mcp__memory__propose_hypothesis` / `mcp__memory__attach_evidence` to keep the graph live.
```

`.claude/skills/debug-sop/SKILL.md`:
```markdown
---
name: debug-sop
description: Systematic debugging. Use when a script errors or produces unexpected results.
---

# Debug SOP

1. Call `mcp__memory__match_signatures` with the error message. Similar past failure? Use that resolution first.
2. If no match: minimal reproduction, then bisect.
3. On resolution: always call `mcp__memory__record_failure` with trigger/symptom/cause/resolution.
```

`.claude/skills/writeup-sop/SKILL.md`:
```markdown
---
name: writeup-sop
description: Writing reports / papers. Use when producing any .md file that makes claims about experimental results.
---

# Writeup SOP

HARD RULE: every numeric claim in a report must be traceable via `mcp__verify__check_provenance`. The PreToolUse hook will block unprovenanced claims on file write.

Workflow:
1. List every claim you want to make.
2. For each, call `mcp__verify__check_provenance`. Missing → re-run or remove the claim.
3. Write the report.
```

**Verification**: in a Claude Code session, ask `@researcher propose three hypotheses about dropout and ViT scaling`. Confirm the subagent is invoked and its tool list is enforced.

---

### Phase 2 — memory-mcp v0.1 (2–3 days)

**Goal**: a running MCP server exposing 7 tools backed by SQLite. No literature compression yet — just structure.

#### Schema (`src/memory_mcp/schema.sql`)

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Hypothesis graph (append-only)
CREATE TABLE IF NOT EXISTS mem_nodes (
  node_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('question','hypothesis','experiment','evidence','conclusion')),
  text TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','refuted','superseded','archived')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT,
  parent_id TEXT REFERENCES mem_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS mem_edges (
  edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
  src TEXT NOT NULL REFERENCES mem_nodes(node_id),
  dst TEXT NOT NULL REFERENCES mem_nodes(node_id),
  relation TEXT NOT NULL CHECK(relation IN ('refines','contradicts','supports','refutes','supersedes','blocks')),
  rationale TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON mem_edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON mem_edges(dst);

-- Failure ledger
CREATE TABLE IF NOT EXISTS mem_failures (
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  symptom TEXT NOT NULL,
  root_cause TEXT,
  resolution TEXT,
  signature TEXT,
  seen_count INTEGER DEFAULT 1,
  first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
  last_seen TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS mem_failures_fts USING fts5(
  trigger, symptom, root_cause, resolution,
  content='mem_failures', content_rowid='failure_id'
);

CREATE TRIGGER IF NOT EXISTS mem_failures_ai AFTER INSERT ON mem_failures BEGIN
  INSERT INTO mem_failures_fts(rowid, trigger, symptom, root_cause, resolution)
  VALUES (new.failure_id, new.trigger, new.symptom, new.root_cause, new.resolution);
END;

-- Literature (metadata stub; extended with compressed fields in Phase 6 — see section 6.3)
CREATE TABLE IF NOT EXISTS mem_lit (
  paper_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT,
  abstract TEXT,
  metadata TEXT,           -- JSON: {arxiv_id, doi, authors, year, venue, ...}
  trust_level REAL DEFAULT 0.5,
  added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### Connection helper (`src/memory_mcp/db.py`)

```python
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(".research-agent/state.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

def _ensure_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        con = sqlite3.connect(str(DB_PATH))
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        con.close()

def _connect():
    _ensure_db()
    con = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.row_factory = sqlite3.Row
    return con

@contextmanager
def tx():
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
```

#### Tool surface (`src/memory_mcp/impl.py`)

```python
import uuid
from memory_mcp.db import tx, _connect

TOOL_NAMES = [
    "propose_hypothesis", "attach_evidence", "mark_refuted",
    "get_active_frontier", "get_ancestors",
    "record_failure", "match_signatures",
]

def propose_hypothesis(text: str, parent_id: str | None = None, rationale: str = "") -> dict:
    node_id = f"h_{uuid.uuid4().hex[:10]}"
    with tx() as con:
        con.execute(
            "INSERT INTO mem_nodes(node_id, kind, text, parent_id) VALUES(?,?,?,?)",
            (node_id, "hypothesis", text, parent_id),
        )
        if parent_id:
            con.execute(
                "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
                (parent_id, node_id, "refines", rationale),
            )
    return {"node_id": node_id}

def attach_evidence(node_id: str, evidence_text: str, polarity: str) -> dict:
    assert polarity in ("supports", "refutes")
    ev_id = f"e_{uuid.uuid4().hex[:10]}"
    with tx() as con:
        con.execute(
            "INSERT INTO mem_nodes(node_id, kind, text) VALUES(?,?,?)",
            (ev_id, "evidence", evidence_text),
        )
        con.execute(
            "INSERT INTO mem_edges(src, dst, relation) VALUES(?,?,?)",
            (ev_id, node_id, polarity),
        )
    return {"evidence_id": ev_id}

def mark_refuted(node_id: str, reason: str, evidence_ids: list[str]) -> dict:
    with tx() as con:
        con.execute(
            "UPDATE mem_nodes SET state='refuted' WHERE node_id=?",
            (node_id,),
        )
        # edges to evidence are created via attach_evidence; nothing mutated here
    return {"refuted": node_id, "reason": reason}

def get_active_frontier() -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT node_id, kind, text, created_at FROM mem_nodes "
        "WHERE state='active' AND kind IN ('hypothesis','question') "
        "ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def get_ancestors(node_id: str) -> list[dict]:
    con = _connect()
    result = []
    current = node_id
    while current:
        row = con.execute(
            "SELECT node_id, parent_id, kind, text FROM mem_nodes WHERE node_id=?",
            (current,),
        ).fetchone()
        if not row:
            break
        result.append(dict(row))
        current = row["parent_id"]
    con.close()
    return result

def record_failure(trigger: str, symptom: str, root_cause: str = "", resolution: str = "") -> dict:
    with tx() as con:
        cur = con.execute(
            "INSERT INTO mem_failures(trigger, symptom, root_cause, resolution) VALUES(?,?,?,?)",
            (trigger, symptom, root_cause, resolution),
        )
        fid = cur.lastrowid
    return {"failure_id": fid}

def match_signatures(situation: str, k: int = 5) -> list[dict]:
    con = _connect()
    rows = con.execute(
        """
        SELECT f.failure_id, f.trigger, f.symptom, f.root_cause, f.resolution,
               bm25(mem_failures_fts) AS score
        FROM mem_failures f
        JOIN mem_failures_fts fts ON fts.rowid = f.failure_id
        WHERE mem_failures_fts MATCH ?
        ORDER BY score LIMIT ?
        """,
        (situation, k),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
```

#### Prod + dev entry points

`src/memory_mcp/server.py`:
```python
from fastmcp import FastMCP
import memory_mcp.impl as impl

mcp = FastMCP("memory")

for name in impl.TOOL_NAMES:
    mcp.tool(getattr(impl, name))

if __name__ == "__main__":
    mcp.run()
```

`src/memory_mcp/dev_server.py`:
```python
import importlib, os
from fastmcp import FastMCP
import memory_mcp.impl as impl

mcp = FastMCP("memory-dev")
DEV = os.environ.get("RESEARCH_AGENT_DEV") == "1"

def _wrap(name):
    def wrapper(**kwargs):
        if DEV:
            importlib.reload(impl)
        return getattr(impl, name)(**kwargs)
    wrapper.__name__ = name
    wrapper.__doc__ = getattr(impl, name).__doc__
    return wrapper

for name in impl.TOOL_NAMES:
    mcp.tool(_wrap(name))

if __name__ == "__main__":
    mcp.run()
```

#### Registration in `.claude/settings.json`

```json
{
  "mcpServers": {
    "memory": {
      "command": "uv",
      "args": ["run", "python", "-m", "memory_mcp.dev_server"],
      "env": {"RESEARCH_AGENT_DEV": "1"}
    }
  },
  "hooks": {}
}
```

**Verification**:
```powershell
# Unit test
uv run pytest tests/memory_mcp/

# In a fresh CC session:
# > call mcp__memory__record_failure with a fake failure
# > call mcp__memory__match_signatures with similar text
# > confirm the failure is returned ranked first
```

---

### Phase 3 — verify-mcp v0.1 (2 days)

**Goal**: Leakage detection and provenance tool surface. No seed_perturb / held_out budget yet.

#### `src/verify_mcp/leakage.py` — AST scanner

```python
import ast
from dataclasses import dataclass

@dataclass
class Finding:
    rule: str
    line: int
    message: str

RISKY_IO = {"open", "read_csv", "read_parquet", "load", "loadtxt", "read_json"}

def scan_python(src: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [Finding("syntax", e.lineno or 0, str(e))]

    # Rule 1: scaler fit before split
    # Rule 2: fit() on concatenated train+test
    # Rule 3: eval on test during training loop
    # Rule 4: held-out path access

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", ""))

            # held-out path access
            if name in RISKY_IO and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if "held_out" in arg.value or ".research-agent" in arg.value:
                        findings.append(Finding(
                            "heldout_access", node.lineno,
                            f"{name}() reads path containing held-out marker: {arg.value!r}"
                        ))

            # fit on pd.concat([train, test]) style
            if name == "fit" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Call):
                    arg_name = getattr(arg.func, "attr", getattr(arg.func, "id", ""))
                    if arg_name in ("concat", "vstack", "hstack"):
                        findings.append(Finding(
                            "fit_on_concatenated", node.lineno,
                            f"fit() called on result of {arg_name}() — possible train+test leakage"
                        ))

    return findings

def scan_file(path: str) -> list[Finding]:
    return scan_python(open(path, encoding="utf-8").read())
```

#### `src/verify_mcp/impl.py`

```python
import json
from pathlib import Path
from datetime import datetime
from verify_mcp.leakage import scan_file, scan_python
from memory_mcp.db import tx, _connect  # share the same DB

TOOL_NAMES = ["leakage_check", "record_provenance", "check_provenance"]

def leakage_check(script_path: str | None = None, script_text: str | None = None) -> dict:
    assert script_path or script_text
    findings = scan_file(script_path) if script_path else scan_python(script_text)
    return {
        "clean": len(findings) == 0,
        "findings": [
            {"rule": f.rule, "line": f.line, "message": f.message}
            for f in findings
        ],
    }

def record_provenance(claim: str, value: str, session_id: str, source_command: str = "") -> dict:
    with tx() as con:
        con.execute(
            """INSERT INTO ver_provenance(claim, value, session_id, source_command, created_at)
               VALUES(?,?,?,?,?)""",
            (claim, value, session_id, source_command, datetime.utcnow().isoformat()),
        )
    return {"recorded": True}

def check_provenance(claim: str) -> dict:
    con = _connect()
    row = con.execute(
        "SELECT * FROM ver_provenance WHERE claim=? ORDER BY created_at DESC LIMIT 1",
        (claim,),
    ).fetchone()
    con.close()
    if row:
        return {"status": "found", "evidence": dict(row)}
    return {"status": "missing"}
```

#### Add `ver_*` tables to schema

Extend `src/memory_mcp/schema.sql` (or create `src/verify_mcp/schema.sql` that runs alongside):

```sql
CREATE TABLE IF NOT EXISTS ver_provenance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claim TEXT NOT NULL,
  value TEXT,
  session_id TEXT,
  source_command TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prov_claim ON ver_provenance(claim);
CREATE INDEX IF NOT EXISTS idx_prov_session ON ver_provenance(session_id);
```

**Verification**:

```powershell
# Unit test: leakage detector against fixtures
uv run pytest tests/verify_mcp/test_leakage.py

# Fixture example:
# tests/verify_mcp/fixtures/leaky_scaler.py  (should trigger 1 finding)
# tests/verify_mcp/fixtures/clean_pipeline.py (should be clean)
```

---

### Phase 4 — Hooks wiring (1 day)

**Goal**: 4 hook scripts + settings.json wiring that actually fires in CC.

#### `.claude/hooks/intervention_pump.py`
```python
#!/usr/bin/env python
"""
Runs on Stop and UserPromptSubmit.
Drains undelivered rows from cockpit_interventions and injects them as additionalContext.
"""
import json, sys, sqlite3
from pathlib import Path

DB = Path(".research-agent/state.db")

def drain():
    if not DB.exists():
        return None
    con = sqlite3.connect(str(DB), timeout=2.0)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, kind, target, payload FROM cockpit_interventions "
            "WHERE delivered_at IS NULL ORDER BY created_at"
        ).fetchall()
    except sqlite3.OperationalError:
        # table doesn't exist yet (cockpit not up)
        con.close()
        return None
    if not rows:
        con.close()
        return None
    ids = [r["id"] for r in rows]
    blocks = [f"[INTERVENTION {r['kind']}] target={r['target']}\n{r['payload']}" for r in rows]
    placeholders = ",".join("?" * len(ids))
    con.execute(
        f"UPDATE cockpit_interventions SET delivered_at = datetime('now') WHERE id IN ({placeholders})",
        ids,
    )
    con.commit()
    con.close()
    return (
        "Cockpit interventions to respect before continuing:\n\n" + "\n\n".join(blocks)
    )

def main():
    _ = json.loads(sys.stdin.read() or "{}")  # we don't actually read the payload
    text = drain()
    if text:
        print(json.dumps({"hookSpecificOutput": {"additionalContext": text}}))
    else:
        print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/hooks/leakage_guard.py`
```python
#!/usr/bin/env python
"""
PreToolUse hook. Blocks Write/Edit/Bash when held-out path patterns are detected.
Bypassed when RESEARCH_AGENT_VERIFY=1 is set (verify-mcp calls).
"""
import json, sys, os, re

HELDOUT_RE = re.compile(
    r"(\.research-agent[\\/]held_out|%USERPROFILE%[\\/]\.research-agent|~[\\/]\.research-agent[\\/]held_out)",
    re.IGNORECASE,
)

def main():
    if os.environ.get("RESEARCH_AGENT_VERIFY") == "1":
        print("{}")
        return
    payload = json.loads(sys.stdin.read() or "{}")
    ti = payload.get("tool_input", {})
    blob = " ".join(str(v) for v in ti.values() if isinstance(v, str))
    m = HELDOUT_RE.search(blob)
    if m:
        print(json.dumps({
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Held-out data access blocked (matched {m.group(0)!r}). "
                    "Use mcp__verify__query_heldout instead."
                )
            }
        }))
        sys.exit(2)
    print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/hooks/destructive_bash_guard.py`
```python
#!/usr/bin/env python
"""PreToolUse Bash guard. Blocks destructive commands unless a confirmation token is present."""
import json, sys, re

DANGEROUS = [
    r"\brm\s+-rf\b",
    r"\bRemove-Item\s+.*-Recurse",
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-fd?x?\b",
    r"\bDROP\s+TABLE\b",
    r"\bDROP\s+DATABASE\b",
    r"\bdel\s+/[sS]\b",
    r"\bformat\s+[a-zA-Z]:",
]

def main():
    payload = json.loads(sys.stdin.read() or "{}")
    cmd = payload.get("tool_input", {}).get("command", "")
    for pat in DANGEROUS:
        if re.search(pat, cmd, re.IGNORECASE):
            if "# CONFIRM_DESTRUCTIVE" not in cmd:
                print(json.dumps({
                    "hookSpecificOutput": {
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"Destructive command blocked ({pat}). "
                            "If intentional, append ' # CONFIRM_DESTRUCTIVE' to the command."
                        )
                    }
                }))
                sys.exit(2)
    print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/hooks/provenance_log.py` (PostToolUse on Bash)
```python
#!/usr/bin/env python
"""Extracts numeric tokens from Bash stdout and writes them to ver_provenance."""
import json, sys, re, sqlite3
from pathlib import Path
from datetime import datetime

DB = Path(".research-agent/state.db")
NUM_RE = re.compile(r"(?:accuracy|acc|loss|f1|auc|rmse|mae|score|p_value|pvalue)[\s:=]+(\-?\d+\.?\d*)", re.IGNORECASE)

def main():
    payload = json.loads(sys.stdin.read() or "{}")
    if payload.get("tool_name") != "Bash":
        print("{}")
        return
    response = payload.get("tool_response", {})
    stdout = response.get("stdout", "") if isinstance(response, dict) else ""
    session_id = payload.get("session_id", "unknown")
    command = payload.get("tool_input", {}).get("command", "")
    matches = NUM_RE.findall(stdout)
    if not matches:
        print("{}")
        return
    if not DB.exists():
        print("{}")
        return
    con = sqlite3.connect(str(DB), timeout=2.0)
    try:
        for v in matches:
            con.execute(
                """INSERT INTO ver_provenance(claim, value, session_id, source_command, created_at)
                   VALUES(?,?,?,?,?)""",
                (f"bash_number", v, session_id, command[:500], datetime.utcnow().isoformat()),
            )
        con.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/hooks/stop_flush.py`
```python
#!/usr/bin/env python
"""Stop hook — emits a sentinel event into cockpit_events for the WebSocket tail."""
import json, sys, sqlite3
from pathlib import Path
from datetime import datetime

DB = Path(".research-agent/state.db")

def main():
    _ = json.loads(sys.stdin.read() or "{}")
    if DB.exists():
        con = sqlite3.connect(str(DB), timeout=2.0)
        try:
            con.execute(
                "INSERT INTO cockpit_events(kind, payload, created_at) VALUES(?,?,?)",
                ("turn_end", "{}", datetime.utcnow().isoformat()),
            )
            con.commit()
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/settings.json` with hooks wired

```json
{
  "mcpServers": {
    "memory": {
      "command": "uv",
      "args": ["run", "python", "-m", "memory_mcp.dev_server"],
      "env": {"RESEARCH_AGENT_DEV": "1"}
    },
    "verify": {
      "command": "uv",
      "args": ["run", "python", "-m", "verify_mcp.dev_server"],
      "env": {"RESEARCH_AGENT_DEV": "1"}
    }
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/leakage_guard.py",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/destructive_bash_guard.py",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/provenance_log.py",
            "timeout": 5
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/intervention_pump.py",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/intervention_pump.py",
            "timeout": 5
          },
          {
            "type": "command",
            "command": "uv run python .claude/hooks/stop_flush.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

**Verification**:
- Write a fake leaky script from the engineer subagent — should be blocked by `leakage_guard.py`.
- Try `rm -rf test/` in Bash — should be blocked unless you append `# CONFIRM_DESTRUCTIVE`.
- Inject a row into `cockpit_interventions` manually, then send any prompt — Claude should receive the intervention as context.

---

### Phase 5 — Cockpit MVP (3–4 days)

**Goal**: Browser at localhost:7777 showing live hypothesis graph + failure ledger, plus ONE interactive button: "reject hypothesis" (writes to `cockpit_interventions`).

#### Backend: `src/cockpit/server.py`

```python
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP

DB = Path(".research-agent/state.db")

# --- cockpit schema bootstrap ---
COCKPIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS cockpit_interventions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,           -- 'reject', 'approve', 'redirect', 'constrain', 'info', 'halt'
  target TEXT,                  -- node_id or claim_id
  payload TEXT,                 -- instruction text
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS cockpit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

def _con():
    con = sqlite3.connect(str(DB), timeout=5.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con

def _ensure():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = _con()
    con.executescript(COCKPIT_SCHEMA)
    con.close()

# --- fastmcp sub-app (for Claude Code) ---
cockpit_mcp = FastMCP("cockpit")

@cockpit_mcp.tool
def push_graph_delta(node_id: str, kind: str, text: str) -> dict:
    """Called by main Claude when a new node is created, for real-time cockpit push."""
    con = _con()
    con.execute(
        "INSERT INTO cockpit_events(kind, payload) VALUES(?,?)",
        ("graph_delta", json.dumps({"node_id": node_id, "kind": kind, "text": text})),
    )
    con.close()
    return {"pushed": True}

# --- FastAPI app ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount fastmcp as sub-app at /mcp
app.mount("/mcp", cockpit_mcp.http_app())

# --- REST endpoints ---
@app.get("/graph")
def get_graph():
    con = _con()
    nodes = [dict(r) for r in con.execute(
        "SELECT node_id, kind, text, state, created_at, parent_id FROM mem_nodes ORDER BY created_at"
    ).fetchall()]
    edges = [dict(r) for r in con.execute(
        "SELECT edge_id, src, dst, relation, rationale FROM mem_edges"
    ).fetchall()]
    con.close()
    return {"nodes": nodes, "edges": edges}

@app.get("/failures")
def get_failures():
    con = _con()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM mem_failures ORDER BY last_seen DESC LIMIT 100"
    ).fetchall()]
    con.close()
    return rows

@app.post("/intervene")
def intervene(kind: str, target: str, payload: str):
    con = _con()
    con.execute(
        "INSERT INTO cockpit_interventions(kind, target, payload) VALUES(?,?,?)",
        (kind, target, payload),
    )
    con.close()
    return {"queued": True}

# --- WebSocket: tail cockpit_events ---
@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    await ws.accept()
    last_id = 0
    try:
        while True:
            con = _con()
            rows = con.execute(
                "SELECT id, kind, payload, created_at FROM cockpit_events WHERE id > ? ORDER BY id",
                (last_id,),
            ).fetchall()
            con.close()
            for r in rows:
                await ws.send_json({
                    "id": r["id"],
                    "kind": r["kind"],
                    "payload": json.loads(r["payload"] or "{}"),
                    "ts": r["created_at"],
                })
                last_id = r["id"]
            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        return
```

Register cockpit-mcp in `.claude/settings.json` as an HTTP MCP pointing at `http://localhost:7777/mcp` (once the cockpit is running) — or add a stdio fallback in v0.2.

#### Frontend scaffolding

```powershell
cd D:\aiscientist\claudescientist\src\cockpit
pnpm create vite frontend --template react-ts
cd frontend
pnpm install
pnpm add @xyflow/react
pnpm add -D tailwindcss @tailwindcss/vite
```

Edit `vite.config.ts`:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173 },
})
```

`src/index.css`:
```css
@import "tailwindcss";
```

`src/hooks/useWebSocket.ts` — auto-reconnecting WS hook (implementation from tech-primer section, ~40 LOC).

`src/components/HypothesisGraph.tsx` — renders `@xyflow/react` from `GET /graph`, updates on WS messages.

`src/components/VerificationTable.tsx` — renders `GET /failures` as a sortable table.

`src/components/InterventionPanel.tsx` — when a graph node is selected, shows 5 typed intervention buttons. Clicking REJECT calls `POST /intervene` with `{kind: 'reject', target: node_id, payload: 'user rejected this hypothesis'}`.

`src/App.tsx` — three-panel layout: left graph (60%), right top failures (40% × 50%), right bottom intervention panel (40% × 50%).

**Run**:
```powershell
# Terminal 1: backend
uv run uvicorn cockpit.server:app --port 7777

# Terminal 2: frontend
cd src\cockpit\frontend
pnpm run dev
# visit http://localhost:5173
```

**Verification**:
- Backend starts cleanly, `GET http://localhost:7777/graph` returns `{nodes: [...], edges: [...]}`.
- Frontend loads, shows empty-state graph.
- From a Claude Code session, call `mcp__memory__propose_hypothesis` — within 500ms the new node appears in the browser.
- Click a node → click REJECT → in the next turn, Claude receives the intervention as `additionalContext`.

---

### Phase 6 — Literature compression (3–4 days)

**Goal**: The `librarian` subagent is fully functional end-to-end — it can discover papers on arxiv/openalex, ingest them with structured compression into `mem_lit`, and query the local index for ranked relevant results.

#### Step 6.1 — Install third-party literature MCPs

```powershell
# arxiv MCP (blazickjp/arxiv-mcp-server): metadata + abstracts
uv tool install arxiv-mcp-server

# openalex MCP (oksure/openalex-research-mcp): 240M works, citation graphs
uv tool install openalex-research-mcp
```

> If either package is not on PyPI under that exact name, install from the git URL: `uv tool install git+https://github.com/blazickjp/arxiv-mcp-server` and `uv tool install git+https://github.com/oksure/openalex-research-mcp`. Pin a specific commit in the command so upgrades are explicit.

#### Step 6.2 — Register in `.claude/settings.json`

Extend `mcpServers`:

```json
{
  "mcpServers": {
    "memory": { "command": "uv", "args": ["run", "python", "-m", "memory_mcp.dev_server"], "env": {"RESEARCH_AGENT_DEV": "1"} },
    "verify": { "command": "uv", "args": ["run", "python", "-m", "verify_mcp.dev_server"], "env": {"RESEARCH_AGENT_DEV": "1"} },
    "arxiv": { "command": "uv", "args": ["tool", "run", "arxiv-mcp-server"] },
    "openalex": { "command": "uv", "args": ["tool", "run", "openalex-research-mcp"] }
  }
}
```

(cockpit is HTTP, registered separately — see Phase 5 notes.)

#### Step 6.3 — Extend schema for compressed literature

Add to `src/memory_mcp/schema.sql` (idempotent — the `IF NOT EXISTS` means running again is safe):

```sql
-- Compressed literature (replaces the v0.1 stub)
CREATE TABLE IF NOT EXISTS mem_lit_compressed (
  paper_id TEXT PRIMARY KEY,               -- arxiv_id or openalex_id
  source TEXT NOT NULL CHECK(source IN ('arxiv','openalex','manual')),
  title TEXT,
  authors TEXT,                            -- JSON array
  year INTEGER,
  venue TEXT,
  problem TEXT,                            -- what problem the paper tackles
  method TEXT,                             -- the method in 2-3 sentences
  claimed_results TEXT,                    -- main quantitative claims
  assumptions TEXT,                        -- explicit assumptions / scope
  limitations TEXT,                        -- stated & inferred
  trust_level REAL DEFAULT 0.5,            -- 0..1 based on venue + reproducibility signals
  relates_to TEXT,                         -- JSON: {paper_id: relation}
  raw_abstract TEXT,
  ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS mem_lit_fts USING fts5(
  title, problem, method, claimed_results,
  content='mem_lit_compressed', content_rowid='rowid'
);
```

#### Step 6.4 — Add tools to `memory_mcp/impl.py`

Add to `TOOL_NAMES`: `"ingest_paper"`, `"query_literature"`, `"find_baselines_for"`.

```python
import json

def ingest_paper(paper_id: str, source: str, structured: dict) -> dict:
    """
    Store a compressed paper. The `structured` dict is produced by the librarian
    subagent from raw arxiv/openalex MCP output + abstract text. Schema:
      { "title", "authors"(list), "year", "venue",
        "problem", "method", "claimed_results",
        "assumptions", "limitations", "trust_level", "raw_abstract" }
    """
    with tx() as con:
        con.execute(
            """INSERT OR REPLACE INTO mem_lit_compressed
               (paper_id, source, title, authors, year, venue, problem, method,
                claimed_results, assumptions, limitations, trust_level, raw_abstract)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                paper_id, source,
                structured.get("title", ""),
                json.dumps(structured.get("authors", [])),
                structured.get("year"),
                structured.get("venue", ""),
                structured.get("problem", ""),
                structured.get("method", ""),
                structured.get("claimed_results", ""),
                structured.get("assumptions", ""),
                structured.get("limitations", ""),
                structured.get("trust_level", 0.5),
                structured.get("raw_abstract", ""),
            ),
        )
    return {"ingested": paper_id}

def query_literature(question: str, k: int = 10) -> list[dict]:
    """Ranked list of papers by BM25 on problem+method+claimed_results, weighted by trust."""
    con = _connect()
    rows = con.execute(
        """
        SELECT p.paper_id, p.title, p.problem, p.method, p.claimed_results,
               p.assumptions, p.limitations, p.trust_level,
               bm25(mem_lit_fts) AS bm25_score
        FROM mem_lit_compressed p
        JOIN mem_lit_fts fts ON fts.rowid = p.rowid
        WHERE mem_lit_fts MATCH ?
        ORDER BY bm25_score * (1.0 / (0.5 + p.trust_level)) LIMIT ?
        """,
        (question, k),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def find_baselines_for(method_description: str, k: int = 5) -> list[dict]:
    """Shortlist of papers whose 'method' field is nearest to the description.
    Used by engineer subagent when picking baselines for comparison."""
    return query_literature(method_description, k=k)
```

#### Step 6.5 — Librarian subagent workflow (refined)

The `librarian` subagent (already written in Phase 1) now has a real end-to-end loop:

1. Receive question from main Claude.
2. `mcp__memory__query_literature(question)` — check what's already ingested.
3. If <3 hits or poor BM25 scores: `mcp__arxiv__search_papers(query)` and `mcp__openalex__search_works(query)`.
4. For each candidate that isn't already in the index, fetch abstract + metadata via those MCPs.
5. Prompt itself to produce the structured extraction (problem/method/claims/assumptions/limitations) — this is the subagent reading its own SOP and producing JSON.
6. Call `mcp__memory__ingest_paper(paper_id, source, structured)` for each.
7. Return a ranked list to main Claude.

The structured-extraction prompt is embedded in the `librarian.md` subagent prompt — no separate Claude API call needed, the subagent *is* Claude.

#### Step 6.6 — Update librarian subagent file

Replace the librarian tool whitelist with the real (non-stub) version:

```markdown
---
name: librarian
description: Discover and structurally ingest papers from arxiv / openalex. Populates the literature index.
tools: Read, WebFetch, mcp__arxiv__search_papers, mcp__arxiv__get_paper, mcp__openalex__search_works, mcp__openalex__get_work, mcp__openalex__get_citations, mcp__memory__ingest_paper, mcp__memory__query_literature
model: sonnet
---

You discover relevant papers for a research question and compress them into structured form.

Workflow for each question:
1. Call `mcp__memory__query_literature` first. Papers already indexed are off-limits.
2. For gaps, query `mcp__arxiv__search_papers` (CS/stats/math) and `mcp__openalex__search_works` (broader). Cap: 10 candidates per call to control cost.
3. For each candidate, fetch the full metadata (arxiv_id/doi, abstract, venue, year).
4. Produce a structured extraction. OUTPUT FORMAT MUST BE VALID JSON matching this schema:
   {"title": str, "authors": [str], "year": int, "venue": str,
    "problem": str (2-3 sentences: what they're solving),
    "method": str (2-3 sentences: how),
    "claimed_results": str (key numbers + direction),
    "assumptions": str (what they assume — be precise),
    "limitations": str (stated + anything I can spot),
    "trust_level": float in [0,1] (based on venue reputation + reproducibility signals),
    "raw_abstract": str}
5. For each, call `mcp__memory__ingest_paper(paper_id, source, structured)`.
6. Return to main Claude: a table of (paper_id, title, 1-line-relevance).

Rules:
- Never fabricate results. If something is unclear in the abstract, leave the field empty.
- Trust level: conference > workshop > arxiv-only. Reproducibility claims (code released, benchmarks) raise it.
- Never ingest a paper you haven't actually read the abstract of.
```

**Verification**:
```powershell
# In a Claude Code session:
# > @librarian find and ingest 5 recent papers on "ViT dropout scaling"
# Expected: 5 rows appear in mem_lit_compressed with non-empty problem/method/assumptions.

# > mcp__memory__query_literature("dropout regularization in vision transformers")
# Expected: ranked list with the 5 new papers near the top.

# > mcp__memory__find_baselines_for("Vision Transformer with per-head dropout")
# Expected: same type of ranking, prioritized by method similarity.
```

---

## 7. v0.2+ Roadmap (deferred)

Ordered by expected value. Note: literature compression is NOT here — it's in v0.1 Phase 6.

1. **seed_perturb + baseline_fairness in verify-mcp** (~3 days)
   - Subprocess runner with `--seed` override, 3 repeats, return mean/std
   - Baseline fairness: compare hyperparameter budgets in two run logs

2. **Research-taste skill & SOP refinement** (~3 days)
   - Elo selection between hypotheses
   - Hypothesis-graph-aware prompt injection in research-sop

3. **Held-out budget enforcement** (~3 days)
   - `register_heldout_dataset` CLI tool that moves data out-of-tree + writes manifest
   - `query_heldout(dataset, model, budget_units)` with budget tracking
   - Manifest drift hard-lock

4. **Prover subagent + lean-lsp-mcp activation** (~1 week)
   - Install lean-lsp-mcp (via `uv tool install lean-lsp-mcp`), install Lean toolchain + mathlib
   - Write test: prover proves sample-mean unbiasedness
   - Activate prover subagent (already stubbed in v0.1 Phase 1)

5. **Multi-project support** (~3 days)
   - Project-scoped `.research-agent/` vs. user-scoped memory
   - Cross-project failure-ledger query

6. **Comparative eval against EvoScientist** (~2 weeks, separate publishing effort)
   - Reproduce their idea-generation benchmark
   - Measure novelty + feasibility delta with our memory layer
   - First paper target

---

## 8. Verification Plan

### Per-phase
Each phase ends with the verification checkbox listed in section 6.

### v0.1 end-to-end smoke test

Run as a real Claude Code session after Phase 5:

```powershell
# Terminal 1: cockpit backend
uv run uvicorn cockpit.server:app --port 7777

# Terminal 2: frontend
cd src\cockpit\frontend && pnpm run dev

# Terminal 3: Claude Code
cd D:\aiscientist\claudescientist
# claude (start CC)
```

In Claude Code:
1. `/research-sop investigate whether dropout rate affects ViT scaling`
   → expect: research-sop skill fires, `librarian` spawned, 5–10 papers ingested into `mem_lit_compressed`, then `researcher` proposes 3 hypotheses. All 3 hypothesis nodes appear in the cockpit graph within 1 second each.
2. Click the first hypothesis node in the cockpit → REJECT button → confirm
   → expect: on Claude's next turn, it receives the intervention as `additionalContext` and drops that hypothesis
3. `@engineer implement the remaining hypothesis as a MNIST-proxy training script`
   → expect: leakage_guard does not block clean code; `provenance_log` captures training numbers from Bash stdout
4. Deliberately ask engineer to write a script with `fit()` on `pd.concat([train, test])`
   → expect: `mcp__verify__leakage_check` flags it; file is blocked on Write via `leakage_guard.py`
5. Try `rm -rf tests/` in a Bash block
   → expect: `destructive_bash_guard` blocks it; appending ` # CONFIRM_DESTRUCTIVE` allows it through
6. `mcp__memory__query_literature("dropout in ViT")`
   → expect: ranked list of ingested papers with structured fields visible
7. End session, restart Claude Code, start a new session
   → expect: the graph state in the cockpit persists; `mcp__memory__match_signatures` returns prior-session failures; literature index is intact

### Regression tests

- `tests/memory_mcp/test_graph.py` — append-only invariants, ancestor walk
- `tests/memory_mcp/test_failures.py` — FTS5 match recall on synthetic failures
- `tests/verify_mcp/test_leakage.py` — detector on labeled leaky/clean fixtures
- `tests/hooks/test_intervention_pump.py` — drain semantics with mocked SQLite
- `tests/e2e/test_smoke.py` — spawns all servers via subprocess, asserts happy path

---

## 9. Resolved Decisions

All four open questions from the initial design have been answered:

- **D1 — Python package management**: ✅ `uv`. All hooks and MCP servers launched via `uv run python -m <module>` for deterministic environment on Windows. `uv.lock` pins the dependency graph.
- **D2 — v0.1 scope**: ✅ Phases 0–6 (scaffold → literature compression). ~15–18 working days. Defers only the heavy items (seed_perturb, held-out budget, lean prover, multi-project) to v0.2+ where they can be informed by real usage.
- **D3 — Literature MCPs strategy**: ✅ Install `arxiv-mcp-server` and `openalex-research-mcp` as-is via `uv tool install`, register in `.claude/settings.json` alongside our own MCPs. Our `memory-mcp` adds a single `ingest_paper` tool that accepts structured extraction output from the librarian subagent. Zero third-party maintenance cost, clean separation of concerns.
- **D4 — Cockpit-MCP transport**: ✅ HTTP at `http://localhost:7777/mcp`. The fastmcp sub-app is mounted inside the same uvicorn process as the FastAPI REST + WebSocket server. One process, one SQLite connection pool, one `uv run uvicorn` command. When the cockpit is down, Claude Code shows the MCP as unavailable; that's an acceptable degraded mode.

Two remaining open items that can be decided during execution (not blockers):

- **Pinned version of `arxiv-mcp-server` and `openalex-research-mcp`**: pick the latest stable tag at Phase 6 start, record the commit hash in `pyproject.toml` comments.
- **Frontend: pnpm vs npm vs yarn**: `pnpm` recommended for speed but any works. Decide at Phase 5 start based on whatever is already installed.

---

## 10. References

- Claude Code docs: https://docs.claude.com/en/docs/claude-code
  - Hooks reference, Subagents, Skills, settings.json
- fastmcp: https://github.com/jlowin/fastmcp
- MCP protocol: https://modelcontextprotocol.io
- uv: https://docs.astral.sh/uv/
- @xyflow/react: https://reactflow.dev/
- Tailwind v4 + Vite: https://tailwindcss.com/docs/installation/using-vite
- lean-lsp-mcp: https://github.com/oOo0oOo/lean-lsp-mcp
- arxiv-mcp-server: https://github.com/blazickjp/arxiv-mcp-server
- openalex-research-mcp: https://github.com/oksure/openalex-research-mcp
- Anthropic official memory MCP (for contrast): https://github.com/modelcontextprotocol/servers/tree/main/src/memory
