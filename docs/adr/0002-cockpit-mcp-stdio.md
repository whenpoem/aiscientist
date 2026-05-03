# ADR 0002: Cockpit MCP runs over stdio, not HTTP

- **Status**: Accepted (v0.2)
- **Date**: 2026-04

## Context

In v0.1 the cockpit was a FastAPI + uvicorn process that mounted a fastmcp
sub-app at `/mcp`. Claude Code talked to the cockpit MCP over HTTP at
`http://localhost:7777/mcp`. This worked but produced two recurring
problems:

1. The user had to remember to start the cockpit process **before** Claude
   Code, otherwise the MCP transport would time out.
2. The fastmcp HTTP sub-app collided with FastAPI's `app.mount("/", ...)`
   pattern in subtle ways (404s being absorbed silently). The v0.1 code
   review flagged this as a real bug.

When v0.2 dropped the browser frontend (see ADR 0003) the only reason to
keep an HTTP transport disappeared.

## Decision

The cockpit exposes its MCP server over **stdio**, identical to the memory
and verify MCPs. Registration in `.claude/settings.json` is just:

```json
"cockpit": {
  "command": "uv",
  "args": ["run", "python", "-m", "cockpit.mcp_server"]
}
```

There is no HTTP transport, no port to open, and no separate process the
user has to start.

## Consequences

### Positive

- The cockpit MCP shares the same lifecycle as memory and verify: Claude
  Code spawns it on session start. No bootstrap order to remember.
- The mount-collision bug is gone by construction.
- Removing FastAPI / uvicorn / starlette from the dependency surface
  shrinks `uv sync` time and cuts a class of CORS / shutdown bugs.
- The TUI (Terminal B) and the cockpit MCP (spawned by Claude Code) are
  now two separate processes that communicate exclusively through SQLite,
  which makes the data flow easier to reason about.

### Negative

- The cockpit MCP cannot be accessed by anything that does not spawn it
  via stdio. If a future use case wants remote access we will have to
  re-add an HTTP transport at that point.
- The TUI itself is no longer reachable over the network, even though
  parts of its data layer could be served. We treat this as a feature.

### Alternatives considered

- **Keep HTTP for the cockpit MCP only** - lost because the bootstrap
  burden (start cockpit before Claude Code) was the most-cited friction
  in v0.1 use.
- **Switch to a unix socket** - lost because Windows is the target and we
  did not want a different transport per OS.

## References

- Originating discussion: [`docs/archive/plan-v0.2.md`](../archive/plan-v0.2.md)
  sections 2.2 and 5.
- Implementation: [`src/cockpit/mcp_server.py`](../../src/cockpit/mcp_server.py).
- Wiring: [`.claude/settings.json`](../../.claude/settings.json).
