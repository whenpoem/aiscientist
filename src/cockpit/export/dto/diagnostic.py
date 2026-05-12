"""DiagnosticReport: the latest diagnostic manifest for a proposition.

Lists every snippet entry in the manifest with its diagnosis verdict
and (when applicable) the candidate failure id it matched against in
the cross-domain ledger. Renderers turn the snippet list into a
numbered checklist; humans use it to decide whether to re-segment,
re-diagnose, or apply correction.
"""

from __future__ import annotations

import json
import sqlite3

from claudescientist.runtime import connect_sqlite, now_utc_iso, state_db_path
from cockpit.export.dto.base import Report, ReportSection


def _connect() -> sqlite3.Connection:
    return connect_sqlite(state_db_path())


def _short(node_id: str) -> str:
    if "_" not in node_id:
        return node_id[:10]
    prefix, suffix = node_id.split("_", 1)
    return f"{prefix}_{suffix[:6]}"


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    return con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone() is not None


def _fetch_latest_manifest_for_proposition(
    con: sqlite3.Connection, proposition_id: str
) -> dict | None:
    """Find the latest manifest under any proof_skeleton descendant of the
    proposition. Returns None when no manifest exists yet."""
    if not _table_exists(con, "prv_diagnostic_manifests"):
        return None
    row = con.execute(
        """
        WITH RECURSIVE descendants(node_id, parent_id, kind, depth) AS (
          SELECT node_id, parent_id, kind, 0
          FROM mem_nodes WHERE node_id = ?
          UNION ALL
          SELECT child.node_id, child.parent_id, child.kind, descendants.depth + 1
          FROM mem_nodes child
          JOIN descendants ON child.parent_id = descendants.node_id
        )
        SELECT m.manifest_id, m.draft_id, m.status, m.items_json,
               m.created_at, m.finalized_at
        FROM prv_diagnostic_manifests m
        JOIN descendants d ON d.node_id = m.draft_id
        WHERE d.kind = 'proof_skeleton'
        ORDER BY m.manifest_id DESC
        LIMIT 1
        """,
        (proposition_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def build_diagnostic(node_id: str) -> Report:
    """Assemble a DiagnosticReport for the given proposition node."""
    con = _connect()
    try:
        prop_row = con.execute(
            "SELECT node_id, kind, text FROM mem_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if prop_row is None:
            raise ValueError(f"unknown node: {node_id!r}")
        prop = dict(prop_row)
        if prop["kind"] != "proposition":
            raise ValueError(
                f"diagnostic reports target propositions; got {prop['kind']!r}"
            )

        sections: list[ReportSection] = [
            ReportSection(
                key="proposition",
                title="Proposition",
                body=prop["text"],
            )
        ]

        manifest = _fetch_latest_manifest_for_proposition(con, node_id)
        if manifest is None:
            sections.append(
                ReportSection(
                    key="status",
                    title="Status",
                    body="No diagnostic manifest registered for this proposition.",
                )
            )
        else:
            sections.append(
                ReportSection(
                    key="status",
                    title="Latest manifest",
                    body=(
                        f"manifest id: {manifest['manifest_id']}\n"
                        f"draft id: {manifest['draft_id']}\n"
                        f"status: {manifest['status']}\n"
                        f"created at: {manifest['created_at']}\n"
                        f"finalized at: {manifest['finalized_at'] or '-'}"
                    ),
                    meta={
                        "manifest_id": int(manifest["manifest_id"]),
                        "status": manifest["status"],
                    },
                )
            )
            try:
                items = json.loads(manifest["items_json"] or "{}").get("entries", [])
            except (TypeError, ValueError):
                items = []
            if items:
                lines: list[str] = []
                for idx, entry in enumerate(items, start=1):
                    snippet_id = entry.get("snippet_id", "-")
                    is_flawed = entry.get("is_flawed", False)
                    cause = entry.get("root_cause", "")
                    marker = "✗" if is_flawed else "✓"
                    lines.append(
                        f"  {idx}. {marker} {_short(str(snippet_id))}  {cause or '-'}"
                    )
                sections.append(
                    ReportSection(
                        key="entries",
                        title=f"Snippet entries ({len(items)})",
                        body="\n".join(lines),
                    )
                )
            else:
                sections.append(
                    ReportSection(
                        key="entries",
                        title="Snippet entries",
                        body="(no entries recorded)",
                    )
                )
    finally:
        con.close()

    title = f"Diagnostic: {_short(node_id)}"
    return Report(
        kind="diagnostic",
        node_id=node_id,
        title=title,
        generated_at=now_utc_iso(),
        sections=tuple(sections),
    )
