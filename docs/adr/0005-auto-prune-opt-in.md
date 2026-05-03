# ADR 0005: Auto-prune is dry-run by default; opt-in via env var

- **Status**: Accepted (v3.0)
- **Date**: 2026-04

## Context

Once the Bradley-Terry layer (ADR 0004) gave us 95% intervals on
hypothesis strength, the next obvious automation was: "if a hypothesis's
upper confidence bound is far below the leader, pause it automatically".
The user's `创新点.md` explicitly asked for this.

But automatic state mutation in a research tournament is dangerous. A
single noisy run, a bug in the BT update math, or a misconfigured
threshold could silently kill an entire branch of research. Recovering
would require digging through the cockpit event stream and manually
calling `resume_branch` for each one - and only **if** the user noticed.

We wanted the capability without the risk.

## Decision

`suggest_pause_low_strength(ucb_threshold, min_comparisons=6)` is
**dry-run by default**:

- It always emits `branch_pause_suggested` events for every candidate so
  the cockpit lights up and the user can see what would happen.
- It only flips `mem_bt_ratings.status` to `paused` (and emits
  `branch_paused`) when the env var `RESEARCH_AGENT_AUTO_PRUNE` is truthy
  (anything other than empty / `0` / `false`).
- `resume_branch(node_id, reason)` reverses any pause and emits
  `branch_promoted`. It is the only allowed reversal path.

The env var is the explicit handoff. A user who has watched dry-run
suggestions for a while and trusts them sets it once at session start.
Everyone else gets advisory output until they actively choose otherwise.

## Consequences

### Positive

- Default behavior is safe: no destructive automation without explicit
  consent.
- Power users can opt in for a single session without changing code.
- The cockpit always shows what *would* be pruned, so the user can
  audit the threshold without ever risking real state.
- Pause is reversible by construction (`resume_branch`), so even when
  auto-prune is on the failure mode is recoverable.

### Negative

- New users may not realise the suggestions can be acted on automatically
  unless they read the docs. Mitigated by the cockpit displaying `auto`
  vs `dry_run` in the suggested event payload.
- We pay the cost of computing the suggestions every time, even when
  nothing will change. Acceptable; the SQL is one indexed scan.
- Two code paths in the same function; the auto branch is rarely
  exercised in tests. We added explicit auto-mode tests in
  `tests/memory_mcp/test_pruning.py` to compensate.

### Alternatives considered

- **Always auto-prune** - lost because of the recovery cost on a single
  bad threshold or bug.
- **Never auto-prune; only suggest** - lost because the user explicitly
  asked for autonomous behavior eventually.
- **Per-branch opt-in** - lost as overengineering; one global env var is
  enough at single-user scale.

## References

- Originating discussion: [`docs/archive/plan-v3.0.md`](../archive/plan-v3.0.md)
  sections 1 and 4.
- Implementation: [`src/memory_mcp/tools/bt.py`](../../src/memory_mcp/tools/bt.py)
  (`suggest_pause_low_strength`, `_auto_prune_enabled`, `resume_branch`).
- Tests: [`tests/memory_mcp/test_pruning.py`](../../tests/memory_mcp/test_pruning.py).
