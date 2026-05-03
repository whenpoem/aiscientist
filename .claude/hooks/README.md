# .claude/hooks - Lifecycle hooks

Short-lived Python scripts that Claude Code spawns at lifecycle events. They
run as subprocesses, read JSON from stdin, and emit JSON on stdout. Each
hook is mechanical and mandatory: safety-critical behavior should NOT depend
on the model remembering to invoke a tool.

## Wiring

All hooks are registered in `.claude/settings.json` under the `hooks`
section. The matchers and event names there are the source of truth; the
table below is a human summary.

| Hook script | Event | Tool matcher | Effect |
|---|---|---|---|
| `leakage_guard.py` | PreToolUse | `Read|Write|Edit|Bash` | Deny tool calls whose paths resolve into a registered sequestered dataset; block markdown writes that name unprovenanced metric values. |
| `destructive_bash_guard.py` | PreToolUse | `Bash` | Deny destructive commands (`rm -rf`, `git reset --hard`, etc.) unless `# CONFIRM_DESTRUCTIVE` is in the command. |
| `provenance_log.py` | PostToolUse | `Bash` | Extract numeric tokens from stdout via `extract_metric_tokens` and write them to `ver_provenance`. |
| `intervention_pump.py` | UserPromptSubmit + Stop | (any) | Drain rows from `cockpit_interventions` and inject as `additionalContext` for the next turn. |
| `stop_flush.py` | Stop | (any) | Emit a `turn_end` cockpit event. |

## Critical invariants

- **Idempotency.** Every hook must tolerate being invoked twice on the same
  payload without producing different state. Stop is fired multiple times
  in some sessions; `intervention_pump` already deduplicates via
  `delivered_at`.
- **Graceful degradation.** If `.research-agent/state.db` is missing or
  malformed (typical on first run), the hook must exit cleanly with an
  empty JSON object. The fail-open default is intentional: we never want a
  broken DB to wedge the entire Claude Code session.
- **No business imports at the top of `leakage_guard.py` or
  `provenance_log.py`.** Both consume `METRIC_RE` and
  `extract_metric_tokens` from `claudescientist.runtime`, NOT from
  `verify_mcp.provenance`. The reverse direction was the v3.0 perforation
  that v3.1 closed.

## What writes which table from a hook

| Hook | Reads | Writes |
|---|---|---|
| `leakage_guard.py` | `ver_heldout_budgets.heldout_path`, `ver_provenance.value` | (none) |
| `destructive_bash_guard.py` | (none) | (none) |
| `provenance_log.py` | (none) | `ver_provenance` |
| `intervention_pump.py` | `cockpit_interventions` | `cockpit_interventions.delivered_at` |
| `stop_flush.py` | (none) | `cockpit_events` (`turn_end`) |

## Do NOT

- Add a long-running process or an HTTP server to a hook. They are spawned
  per event; cold-start cost matters.
- Have a hook print anything other than the JSON contract on stdout. Other
  messages should go to stderr.
- Bypass `query_heldout` to read sequestered data. The leakage guard
  itself depends on this restriction holding everywhere else.
- Reach across into `verify_mcp.provenance` for `METRIC_RE` /
  `extract_metric_tokens`. Use `claudescientist.runtime` instead.
