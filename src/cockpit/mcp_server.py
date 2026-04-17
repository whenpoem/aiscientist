"""StdIO MCP server for the cockpit."""

from __future__ import annotations

from fastmcp import FastMCP

from . import data

mcp = FastMCP("cockpit")


@mcp.tool
def push_graph_delta(node_id: str, kind: str, text: str) -> dict:
    """Append a graph-delta event for the TUI to consume."""
    event_id = data.record_event(
        "graph_delta",
        {"node_id": node_id, "kind": kind, "text": text},
    )
    return {"ok": True, "event_id": event_id}


@mcp.tool
def queue_intervention(kind: str, target: str | None = None, payload: str = "") -> dict:
    """Write an intervention row using the shared cockpit tables."""
    result = data.write_intervention(kind, target, payload)
    return {"ok": True, **result}


@mcp.tool
def record_note(text: str) -> dict:
    """Compatibility helper for scripted note-taking."""
    event_id = data.record_event("note", {"text": text})
    return {"ok": True, "event_id": event_id}


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
