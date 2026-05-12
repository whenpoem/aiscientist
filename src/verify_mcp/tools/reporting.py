"""Reporting tool surface for verify_mcp (v4.2.0a2 / ADR 0009).

Thin facade over ``cockpit.export.generate`` so the reviewer agent
(and any other MCP consumer that needs evidence-chain snapshots) can
ask for a report file without depending on the cockpit package
directly. The tool returns the list of written paths so the caller
can cite them in their JSON output.

The MCP boundary deliberately stays narrow — this tool exports one
report at a time. Composing several reports is the caller's job
(invoking the tool repeatedly).
"""

from __future__ import annotations

from typing import Sequence


def export_report(
    kind: str,
    node_id: str,
    formats: Sequence[str] = ("md",),
) -> dict:
    """Generate a report file from cockpit state.

    ``kind`` is one of ``closure``, ``draft``, ``diagnostic``,
    ``portfolio``, ``cascade``. ``node_id`` references a row in
    ``mem_nodes`` — usually a proposition (proof side) or a
    hypothesis (empirical side). ``formats`` is a list of
    ``md`` / ``html``; defaults to ``["md"]``.

    Returns ``{"paths": ["reports/...", ...]}``. Raises ``ValueError``
    for unknown kind / format / node id.

    Side effects: writes one file per format under ``reports/`` and
    inserts a row per file in ``cockpit_reports`` (the cockpit's
    Reports tab will pick them up on the next refresh tick).
    """
    # Lazy import so the verify_mcp module doesn't pull cockpit at
    # import time — keeps the server startup independent of cockpit
    # availability for users who run a headless setup.
    from cockpit.export import generate

    paths = generate(
        kind,
        node_id,
        formats=tuple(formats),
        generated_by="verify_mcp.export_report",
    )
    return {"paths": [str(path) for path in paths]}
