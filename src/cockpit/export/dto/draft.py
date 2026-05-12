"""DraftReport: the latest LaTeX draft for a proposition.

Walks the proof_skeleton descendants under a proposition and picks
the deepest / newest as the latest draft. The DTO returns that
draft's text plus segmentation metadata (snippet count if it has
been segmented).
"""

from __future__ import annotations

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


def _fetch_latest_draft(con: sqlite3.Connection, proposition_id: str) -> dict | None:
    """Return the deepest / newest proof_skeleton descendant of ``proposition_id``."""
    row = con.execute(
        """
        WITH RECURSIVE descendants(node_id, kind, text, parent_id, created_at, depth) AS (
          SELECT node_id, kind, text, parent_id, created_at, 0
          FROM mem_nodes WHERE node_id = ?
          UNION ALL
          SELECT child.node_id, child.kind, child.text, child.parent_id,
                 child.created_at, descendants.depth + 1
          FROM mem_nodes child
          JOIN descendants ON child.parent_id = descendants.node_id
        )
        SELECT node_id, text, depth, created_at
        FROM descendants
        WHERE kind = 'proof_skeleton'
        ORDER BY depth DESC, created_at DESC, node_id DESC
        LIMIT 1
        """,
        (proposition_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _fetch_snippets(con: sqlite3.Connection, draft_id: str) -> list[dict]:
    """Return proof_snippet children of ``draft_id`` in document order."""
    rows = con.execute(
        """
        SELECT node_id, text, created_at
        FROM mem_nodes
        WHERE parent_id = ? AND kind = 'proof_snippet'
        ORDER BY created_at, node_id
        """,
        (draft_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def build_draft(node_id: str) -> Report:
    """Assemble a DraftReport for the given proposition node."""
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
                f"draft reports target propositions; got kind {prop['kind']!r}"
            )

        sections: list[ReportSection] = [
            ReportSection(
                key="proposition",
                title="Proposition",
                body=prop["text"],
            )
        ]

        latest = _fetch_latest_draft(con, node_id)
        if latest is None:
            sections.append(
                ReportSection(
                    key="draft_status",
                    title="Draft status",
                    body="No proof skeleton has been registered under this proposition yet.",
                )
            )
        else:
            sections.append(
                ReportSection(
                    key="draft_body",
                    title=f"Latest draft ({_short(latest['node_id'])})",
                    body=latest["text"],
                    meta={
                        "draft_id": latest["node_id"],
                        "depth": int(latest["depth"]),
                    },
                )
            )
            snippets = _fetch_snippets(con, latest["node_id"])
            if snippets:
                snippet_lines = [
                    f"  {idx + 1}. {_short(row['node_id'])}\n      {row['text']}"
                    for idx, row in enumerate(snippets)
                ]
                sections.append(
                    ReportSection(
                        key="snippets",
                        title=f"Segmentation ({len(snippets)} snippets)",
                        body="\n".join(snippet_lines),
                    )
                )
    finally:
        con.close()

    title = f"Draft: {_short(node_id)}"
    return Report(
        kind="draft",
        node_id=node_id,
        title=title,
        generated_at=now_utc_iso(),
        sections=tuple(sections),
    )
