"""StdIO MCP server for the cockpit."""

from __future__ import annotations

import re

from fastmcp import FastMCP

from . import data
from .phase import PHASES

mcp = FastMCP("cockpit")


@mcp.tool
def push_graph_delta(node_id: str, kind: str, text: str) -> dict:
    """Append a graph-delta event for the TUI to consume."""
    event_id = data.record_event(
        "graph_delta",
        {"node_id": node_id, "kind": kind, "text": text},
        source="cockpit_mcp",
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
    event_id = data.record_event("note", {"text": text}, source="cockpit_mcp")
    return {"ok": True, "event_id": event_id}


# v5.0 Activity Streaming atomic tools. Both are passive descriptive
# signals — they emit one ``cockpit_events`` row and return. They do
# NOT change derived phase / focus directly; the cockpit's tick reads
# the same table and re-derives. Per ADR 0007 these are single-verb
# atomic tools — no internal chaining, no enforced ordering, agents
# remain free to skip them. See ``docs/adr/0011-cockpit-activity-streaming.md``.

_NODE_ID_RE = re.compile(r"^[a-z]+_[a-z0-9_]+$")
_SCOPE_RE = re.compile(
    r"^(session|node:[a-z]+_[a-z0-9_]+|branch:[a-z0-9_]+)$"
)


@mcp.tool
def set_phase(
    phase: str,
    focus_nodes: list[str] | None = None,
    intent: str = "",
) -> dict:
    """Record an explicit phase signal that overrides derivation.

    ``phase`` must be one of :data:`cockpit.phase.PHASES` (``idle``,
    ``explore``, ``select``, ``experiment``, ``verify``, ``prove``,
    ``review``, ``narrate``). ``focus_nodes`` is up to 8 mem_node ids
    the agent is currently working on; the cockpit's focus pane
    treats these as a high-confidence hint above the derived
    scoring. ``intent`` is a free-text one-sentence label rendered
    on the phase strip (truncated to 200 chars).

    Returns ``{"ok": True, "event_id": <int>}``. Validation failures
    raise ``ValueError`` so fastmcp surfaces a structured error to
    the caller.
    """
    if phase not in PHASES:
        raise ValueError(
            f"phase must be one of {sorted(PHASES)}; got {phase!r}"
        )
    nodes: list[str] = []
    for n in focus_nodes or []:
        if not isinstance(n, str) or not n.strip():
            continue
        candidate = n.strip()
        if not _NODE_ID_RE.match(candidate):
            raise ValueError(
                f"focus_nodes entry {candidate!r} does not match "
                "^[a-z]+_[a-z0-9_]+$"
            )
        nodes.append(candidate)
        if len(nodes) >= 8:
            break
    # Truncate intent and strip control chars.
    sanitized_intent = "".join(
        ch for ch in str(intent or "") if ch.isprintable() or ch in {" ", "\t"}
    ).strip()[:200]
    event_id = data.record_event(
        "phase_set",
        {
            "phase": phase,
            "focus_nodes": nodes,
            "intent": sanitized_intent,
        },
        source="cockpit_mcp",
    )
    return {"ok": True, "event_id": event_id}


@mcp.tool
def narrate(text: str, scope: str = "session") -> dict:
    """Record a one-sentence agent narration.

    ``text`` must be 1–500 chars after stripping. ``scope`` is one
    of ``"session"``, ``"node:<id>"``, ``"branch:<id>"``. The
    cockpit renders narrations as a ``"narrate``-family activity
    card and, when ``scope`` is ``"session"``, as the third line of
    the phase strip.

    This tool does NOT change derived phase. Use ``set_phase`` for
    that. ``narrate`` is the soft inner-monologue channel: useful
    at branch points (\"why this path and not that\") but it is
    always optional — agents that skip it incur no penalty.
    """
    body = str(text or "").strip()
    if not body:
        raise ValueError("narrate(text=...): text must be non-empty after strip")
    if len(body) > 500:
        body = body[:497] + "…"
    scope_str = str(scope or "session").strip()
    if not _SCOPE_RE.match(scope_str):
        raise ValueError(
            f"scope must match {_SCOPE_RE.pattern!r}; got {scope_str!r}"
        )
    event_id = data.record_event(
        "agent_narration",
        {"text": body, "scope": scope_str},
        source="cockpit_mcp",
    )
    return {"ok": True, "event_id": event_id}


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
