"""Export pipeline — DTO builder + renderer + filesystem + index insert.

This is the only public entry point most callers should need.
``generate(kind, node_id, formats)`` walks the three layers,
writes one file per requested format, inserts a row in
``cockpit_reports``, and emits a ``report_generated`` cockpit event
so the live TUI repaints. The function returns the list of paths
written so the caller can open them in a default app.

The pipeline never crosses layers: it doesn't peek inside renderer
internals, it doesn't peek inside DTO internals. It composes them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

from claudescientist.runtime import (
    connect_sqlite,
    emit_cockpit_event,
    state_db_path,
)
from cockpit.db import ensure as _ensure_cockpit_db
from cockpit.export.dto import BUILDERS
from cockpit.export.dto.base import Report
from cockpit.export.paths import report_path, reports_dir
from cockpit.export.renderers import RENDERERS

KINDS: tuple[str, ...] = tuple(BUILDERS.keys())
FORMATS: tuple[str, ...] = tuple(RENDERERS.keys())


def kinds_for_node_kind(node_kind: str) -> tuple[str, ...]:
    """Return the report kinds that make sense for a given node kind.

    Used by the ExportModal to filter the menu down to relevant
    options. Returning everything when the node kind isn't recognized
    is the safe default — the DTO builder itself enforces the strict
    rules and raises a clear ValueError when a kind doesn't apply.
    """
    if node_kind == "proposition":
        return ("closure", "draft", "diagnostic", "portfolio", "cascade")
    if node_kind == "hypothesis":
        return ("closure", "cascade")
    if node_kind == "proof_skeleton":
        return ("cascade",)
    if node_kind == "proof_snippet":
        return ("cascade",)
    return KINDS


def generate(
    kind: str,
    node_id: str,
    *,
    formats: Sequence[str] = ("md",),
    generated_by: str = "cockpit.export",
) -> list[Path]:
    """Build the report, render each requested format, write the file(s),
    and index them. Returns the list of written paths.

    Raises ``ValueError`` for unknown kind / format, or when the DTO
    builder rejects the node (e.g. asking for a draft report against
    a hypothesis). File write errors propagate as ``OSError`` — the
    caller decides whether to swallow them. The ``cockpit_reports``
    insert and event emit happen inside one transaction so the index
    never lists a file the cockpit didn't successfully announce.
    """
    if kind not in BUILDERS:
        raise ValueError(
            f"unknown report kind {kind!r}; expected one of {sorted(KINDS)}"
        )
    requested = list(formats)
    if not requested:
        raise ValueError("at least one format must be requested")
    for fmt in requested:
        if fmt not in RENDERERS:
            raise ValueError(
                f"unknown format {fmt!r}; expected one of {sorted(FORMATS)}"
            )

    report: Report = BUILDERS[kind](node_id)
    target_dir = reports_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for fmt in requested:
        renderer = RENDERERS[fmt]
        path = report_path(kind, node_id, fmt)
        path.write_text(renderer.render(report), encoding="utf-8")
        written.append(path)

    # Index + emit in a single transaction so the cockpit's event
    # listener never sees a "generated" event with no matching row.
    _ensure_cockpit_db()
    con = connect_sqlite(state_db_path())
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            for fmt, path in zip(requested, written):
                size = path.stat().st_size
                con.execute(
                    """
                    INSERT INTO cockpit_reports(
                      file_path, kind, related_node_id, format, bytes,
                      generated_by, generated_at
                    ) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(file_path) DO UPDATE SET
                      kind = excluded.kind,
                      related_node_id = excluded.related_node_id,
                      format = excluded.format,
                      bytes = excluded.bytes,
                      generated_by = excluded.generated_by,
                      generated_at = excluded.generated_at
                    """,
                    (
                        str(path),
                        report.kind,
                        report.node_id,
                        fmt,
                        size,
                        generated_by,
                        report.generated_at,
                    ),
                )
                emit_cockpit_event(
                    con,
                    "report_generated",
                    {
                        "kind": report.kind,
                        "node_id": report.node_id,
                        "format": fmt,
                        "path": str(path),
                        "bytes": size,
                        "generated_by": generated_by,
                    },
                )
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
    finally:
        con.close()

    return written
