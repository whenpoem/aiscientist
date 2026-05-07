# ADR 0007: Tools / Skills / Hooks layering doctrine

- **Status**: Accepted (v4.0)
- **Date**: 2026-05

## Context

ClaudeScientist exposes capability to Claude Code through three distinct
mechanisms: MCP **tools** (atomic verbs the main model invokes on demand),
**skills** in `.claude/skills/` (markdown SOPs the main model reads when it
needs guidance), and **hooks** in `.claude/hooks/` plus reviewer agent gates
(short-lived processes and structured checks that block lifecycle events).

In v3.0 the boundary among these was implicit. `research-sop` reads like a
6-step pipeline because the markdown enumerates steps in order, but in
practice the main model calls the underlying MCP tools in whatever order
the situation demands — skipping, looping, branching across the empirical
trunk. The only true sequencing constraints are the four hooks and the
reviewer's writeup gate.

ADR 0008 commits the project to a second trunk (proof). StatProver, the
reference product, ships a literal 6-stage pipeline: refine → retrieve →
draft → segment → diagnose → correct, in fixed order. There is a real risk
that the proof trunk imports that ordering as code rather than as advice —
which would change the project's character from "free-form agent with
guardrails" to "scripted pipeline with an LLM driver". The user's stated
preference, and the existing v3.0 design, is the former.

We therefore make the layering explicit, in writing, before the proof
trunk is built. New capabilities must declare which layer they belong to.

## Decision

ClaudeScientist has exactly three capability layers, with the following
contracts:

### Tools — atomic verbs, no enforced ordering

- An MCP tool implements one operation and returns. It does not chain to
  the next tool, does not loop, does not call other tools internally on
  the user's behalf.
- The main model decides which tools to call and in what order. Tool
  outputs are JSON-serialisable dicts; state lives in SQLite.
- "Workflow state" is **inferred from data**, not stored in a state
  machine. If the model wants to know whether a proof has been
  segmented, it queries `mem_nodes` for `kind='proof_snippet'` children.
  We do not introduce `prv_workflow_state` or any equivalent.
- Convenience wrappers that compose multiple atomic tools are allowed,
  but their names and docstrings must declare them as wrappers (e.g.
  `auto_full_proof(...)` calling six atomic tools in sequence). Atomic
  versions remain independently callable.
- Forbidden: a single tool whose name suggests it executes a fixed
  pipeline as the only entry point (e.g. `run_proof_pipeline`).

### Skills — recipes, suggestions, deviation allowed

- A skill is a markdown SOP under `.claude/skills/`. It documents a
  recommended ordering and decision points. The main model reads it
  when relevant; nothing enforces compliance.
- Skills may reference other skills (`$bt-tournament`, `$preregister`).
- Skills must mark optional or skippable steps explicitly so the model
  understands deviation is sanctioned, not exceptional.
- Skill files stay short (the v3.0 examples are 21–48 lines).

### Hooks and reviewer gates — laws, non-negotiable

- A hook (entry under `.claude/hooks/`) or a reviewer-side gate is the
  only mechanism that can block a tool call or refuse a verdict. New
  hooks require an ADR-level justification — they restrict what the main
  model can do.
- v3.0 inventory of laws:
  - `leakage_guard.py` — denies reads/writes into held-out paths.
  - `destructive_bash_guard.py` — denies destructive shell commands
    without an explicit `# CONFIRM_DESTRUCTIVE` marker.
  - `provenance_log.py` — extracts numeric tokens from Bash stdout.
  - `intervention_pump.py` — drains pending cockpit interventions.
  - `stop_flush.py` — emits the `turn_end` event.
  - Reviewer's writeup checklist — refuses `accept` while blockers are
    non-empty (ADR 0006).
- v4.0 adds exactly one law: the reviewer's parallel proof checklist
  (theorem claims need empty diagnostic manifest plus formal proof or
  explicit `unverified` flag; ADR 0008).
- Forbidden: turning a workflow recommendation ("retrieve before
  draft") into a hook just because the recommendation is being skipped
  in practice. The fix for "the model keeps skipping step N" is to
  improve the skill, not to legislate.

### The judgment rule for new capabilities

For any new capability `X`, ask:

1. **Verb?** If `X` is one operation that returns a value, it is a tool.
   This is the default answer for ~99% of new capabilities.
2. **Recipe?** If `X` is "the recommended order to call existing tools
   for situation S", it is a skill.
3. **Law?** If `X` exists to refuse a tool call or to refuse a verdict
   when conditions are violated, and the refusal must hold regardless of
   what the model otherwise wants to do, it is a hook or a reviewer gate.

The ratios should look like the existing inventory: dozens of tools,
single-digit skills, four to six laws.

## Consequences

### Positive

- The proof trunk's eight-to-ten new MCP tools land as independent
  atomic operations. The 6-stage StatProver pipeline becomes the
  recommended ordering written into `prove-sop/SKILL.md`, not code.
- Contributors have a clear judgment rule for where to put new
  capability. The ratio of tool : skill : hook stays stable.
- Future capability creep does not silently pipelinise the system; any
  attempt to add a hook that enforces ordering rather than safety will
  fail this ADR's review.
- Workflow state is inferable from `mem_*` and `prv_*` tables, so any
  client (the cockpit, a future headless loop, a different MCP host)
  can reconstruct progress without a workflow-state daemon.

### Negative

- The main model carries some orchestration burden: it must decide
  which atomic tools to chain. Mitigated by the skills, which are
  exactly that orchestration knowledge in markdown.
- Convenience wrappers and atomic tools both exist, growing the visible
  tool count. Tools file names and docstrings must mark wrappers
  clearly so the catalog stays navigable.
- A genuine business rule that needs enforcement (e.g. "all proofs in
  manuscripts must be Lean-verified") cannot be a skill; it has to
  enter the reviewer's hard rules. We accept that ADR-gating these
  rules is the right friction.

### Alternatives considered

- **Encode the pipeline in code; expose only `run_proof_pipeline`** —
  lost. Predictable but kills the agent's ability to interleave proof
  and empirical work, and discards every cooperation interface the
  shared core was set up to enable.
- **Stateful workflow engine with a `prv_workflow_state` table** — lost
  as overengineering. The data already implies the state; a workflow
  table would duplicate that and create a synchronisation problem.
- **No formal layering; rely on convention** — lost because v4.0 doubles
  the project's surface and conventions that worked at v3.0 scale will
  drift without an explicit doctrine.

## References

- Originating discussion: plan file
  `C:\Users\whenpoem\.claude\plans\snazzy-twirling-donut.md`.
- Sister ADR: [`0008-two-trunk-domain-architecture.md`](0008-two-trunk-domain-architecture.md).
- Existing layering examples: tools under
  [`src/memory_mcp/tools/`](../../src/memory_mcp/tools/) and
  [`src/verify_mcp/tools/`](../../src/verify_mcp/tools/); skills under
  [`.claude/skills/`](../../.claude/skills/); hooks under
  [`.claude/hooks/`](../../.claude/hooks/).
- Reviewer hard rules: [`.claude/agents/reviewer.md`](../../.claude/agents/reviewer.md).
- Architecture §10 ("What this contract intentionally leaves open"):
  this ADR is the partner that pins what the contract closes.
