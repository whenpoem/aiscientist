"""Proof segmentation + diagnostic-manifest opener (P3).

The agent (per ADR 0007) is responsible for splitting a draft into
minimal logical units and passing the snippet list to ``segment_proof``.
This tool's job is purely persistence: write each snippet as a
proof_snippet mem_node under the draft, open a fresh diagnostic manifest
in status='open', and return the ids the agent will use for the
diagnose/correct cycle.
"""

from __future__ import annotations

import json

from prove_mcp.db import tx

from ._common import _emit_event
from .nodes import _insert_node, _new_id


def segment_proof(draft_id: str, snippets: list[str]) -> dict:
    """Persist agent-segmented proof snippets and open a diagnostic manifest.

    Each non-empty entry in ``snippets`` becomes a mem_node(kind=
    'proof_snippet', parent_id=draft_id). A new
    prv_diagnostic_manifests row is created with status='open' and
    items_json='{"entries": []}'; the agent later populates entries via
    :func:`register_diagnosis` and closes the manifest with
    :func:`finalize_manifest`.
    """
    if not isinstance(snippets, list):
        raise ValueError("snippets must be a list of strings")
    cleaned = [s.strip() for s in snippets if isinstance(s, str) and s.strip()]
    if not cleaned:
        raise ValueError("segment_proof requires at least one non-empty snippet")
    snippet_ids: list[str] = []
    with tx() as con:
        draft = con.execute(
            "SELECT node_id, kind FROM mem_nodes WHERE node_id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise ValueError(f"Unknown draft: {draft_id}")
        if draft["kind"] != "proof_skeleton":
            raise ValueError(
                f"segment_proof expects a proof_skeleton draft; got kind={draft['kind']!r}"
            )
        for text in cleaned:
            sid = _new_id("proof_snippet")
            _insert_node(
                con,
                node_id=sid,
                kind="proof_snippet",
                text=text,
                parent_id=draft_id,
            )
            snippet_ids.append(sid)
        cur = con.execute(
            """
            INSERT INTO prv_diagnostic_manifests(draft_id, status, items_json)
            VALUES(?, 'open', ?)
            """,
            (draft_id, json.dumps({"entries": []})),
        )
        manifest_id = int(cur.lastrowid)
        _emit_event(
            con,
            "proof_segmented",
            {
                "draft_id": draft_id,
                "manifest_id": manifest_id,
                "snippet_count": len(snippet_ids),
            },
        )
    return {"manifest_id": manifest_id, "snippet_ids": snippet_ids}


def list_proof_snippets(draft_id: str) -> list[dict]:
    """Return the proof_snippet children of a draft in insertion order.

    Order is taken from SQLite's hidden ``rowid`` (monotonic with insert)
    rather than ``created_at`` because rapid same-transaction inserts
    collide on the seconds-precision timestamp.
    """
    from prove_mcp.db import _connect

    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT rowid AS _rowid, node_id, text, state, created_at
            FROM mem_nodes
            WHERE kind = 'proof_snippet' AND parent_id = ?
            ORDER BY _rowid ASC
            """,
            (draft_id,),
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "node_id": row["node_id"],
            "text": row["text"],
            "state": row["state"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
