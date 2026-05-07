"""Proof-trunk node creators (P3).

prove_mcp owns proposition / proof_skeleton / proof_snippet creation, the
proof-trunk parallels of memory_mcp.propose_hypothesis. Each writer goes
through a shared :func:`_insert_node` helper that:

- generates a kind-prefixed id (prop_, psk_, psnp_) via the same
  ``memory_mcp.tools._common._node_id`` mapping
- INSERTs into mem_nodes with the right kind
- emits a graph_delta cockpit event so the TUI lights up immediately
- for proof_skeleton, also INSERT OR IGNORE into mem_bt_ratings so the
  proof-skeleton leaderboard works on day one (matches the P1 contract)

These tools are the only sanctioned way for the proof trunk to write
into mem_nodes. Direct SQL inserts from prove_mcp code are banned outside
this file (architecture.md §3 / §13).
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from prove_mcp.db import tx

from ._common import _emit_event

_PREFIX = {
    "proposition": "prop",
    "proof_skeleton": "psk",
    "proof_snippet": "psnp",
}


def _new_id(kind: str) -> str:
    prefix = _PREFIX[kind]
    return f"{prefix}_{uuid4().hex[:12]}"


def _insert_node(
    con: sqlite3.Connection,
    *,
    node_id: str,
    kind: str,
    text: str,
    parent_id: str | None,
    created_by: str = "claude",
) -> None:
    if parent_id:
        parent = con.execute(
            "SELECT node_id FROM mem_nodes WHERE node_id = ?",
            (parent_id,),
        ).fetchone()
        if parent is None:
            raise ValueError(f"Unknown parent node: {parent_id}")
    con.execute(
        """
        INSERT INTO mem_nodes(node_id, kind, text, state, created_by, parent_id)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (node_id, kind, text, "active", created_by, parent_id),
    )
    if parent_id:
        con.execute(
            "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
            (parent_id, node_id, "parent_of", ""),
        )
    if kind == "proof_skeleton":
        con.execute(
            "INSERT OR IGNORE INTO mem_bt_ratings(node_id) VALUES(?)",
            (node_id,),
        )


def propose_proposition(text: str, parent_id: str | None = None) -> dict:
    """Create a proposition node (the proof-trunk peer of a hypothesis).

    Use ``parent_id`` to link the proposition under a question node so it
    sits as a sibling of related hypotheses on the unified hypothesis
    tree (architecture.md §13 cooperation interface 1).
    """
    if not (text or "").strip():
        raise ValueError("proposition text must be non-empty")
    node_id = _new_id("proposition")
    with tx() as con:
        _insert_node(
            con,
            node_id=node_id,
            kind="proposition",
            text=text,
            parent_id=parent_id,
        )
        _emit_event(
            con,
            "graph_delta",
            {"node_id": node_id, "kind": "proposition", "text": text},
        )
    return {"node_id": node_id}


def propose_proof_skeleton(
    proposition_id: str,
    text: str,
    note: str = "",
) -> dict:
    """Create a proof_skeleton candidate under a proposition.

    Seeds a mem_bt_ratings row so the skeleton can immediately compete in
    a Bradley-Terry tournament against sibling skeletons (P1 widened
    BT_RANKABLE_KINDS to include proof_skeleton).
    """
    if not (text or "").strip():
        raise ValueError("proof_skeleton text must be non-empty")
    node_id = _new_id("proof_skeleton")
    with tx() as con:
        prop = con.execute(
            "SELECT node_id, kind FROM mem_nodes WHERE node_id = ?",
            (proposition_id,),
        ).fetchone()
        if prop is None:
            raise ValueError(f"Unknown proposition: {proposition_id}")
        if prop["kind"] != "proposition":
            raise ValueError(
                f"propose_proof_skeleton requires a proposition parent; got "
                f"kind={prop['kind']!r}"
            )
        _insert_node(
            con,
            node_id=node_id,
            kind="proof_skeleton",
            text=text,
            parent_id=proposition_id,
        )
        _emit_event(
            con,
            "graph_delta",
            {
                "node_id": node_id,
                "kind": "proof_skeleton",
                "text": text,
                "proposition_id": proposition_id,
                "note": note,
            },
        )
    return {"node_id": node_id}


def register_proof_draft(
    skeleton_id: str,
    draft_text: str,
    note: str = "",
) -> dict:
    """Persist a generated draft as a child proof_skeleton revision.

    Drafts share the ``proof_skeleton`` kind with their parent outline -
    each iteration is a child node so the parent chain encodes revision
    history. The reviewer's writeup gate (P5) walks this chain to find
    the latest version.
    """
    if not (draft_text or "").strip():
        raise ValueError("draft_text must be non-empty")
    node_id = _new_id("proof_skeleton")
    with tx() as con:
        skel = con.execute(
            "SELECT node_id, kind FROM mem_nodes WHERE node_id = ?",
            (skeleton_id,),
        ).fetchone()
        if skel is None:
            raise ValueError(f"Unknown skeleton: {skeleton_id}")
        if skel["kind"] != "proof_skeleton":
            raise ValueError(
                f"register_proof_draft requires a proof_skeleton parent; got "
                f"kind={skel['kind']!r}"
            )
        _insert_node(
            con,
            node_id=node_id,
            kind="proof_skeleton",
            text=draft_text,
            parent_id=skeleton_id,
        )
        _emit_event(
            con,
            "graph_delta",
            {
                "node_id": node_id,
                "kind": "proof_skeleton",
                "text": draft_text,
                "parent_skeleton_id": skeleton_id,
                "note": note,
                "is_draft": True,
            },
        )
    return {"node_id": node_id, "parent_skeleton_id": skeleton_id}


def list_proof_drafts(proposition_id: str, limit: int = 20) -> list[dict]:
    """List proof_skeleton descendants under one proposition.

    Rows are ordered deepest-first, then newest-first. The reviewer uses
    the first row as the latest available draft candidate for the proof
    checklist.
    """
    limit = max(1, min(int(limit), 200))
    from prove_mcp.db import _connect

    con = _connect()
    try:
        prop = con.execute(
            "SELECT node_id, kind FROM mem_nodes WHERE node_id = ?",
            (proposition_id,),
        ).fetchone()
        if prop is None:
            raise ValueError(f"Unknown proposition: {proposition_id}")
        if prop["kind"] != "proposition":
            raise ValueError(
                f"list_proof_drafts expects a proposition; got kind={prop['kind']!r}"
            )
        rows = con.execute(
            """
            WITH RECURSIVE descendants(node_id, kind, text, state, created_at, parent_id, depth)
            AS (
              SELECT node_id, kind, text, state, created_at, parent_id, 0
              FROM mem_nodes
              WHERE node_id = ?
              UNION ALL
              SELECT child.node_id, child.kind, child.text, child.state,
                     child.created_at, child.parent_id, descendants.depth + 1
              FROM mem_nodes child
              JOIN descendants ON child.parent_id = descendants.node_id
            )
            SELECT node_id, kind, text, state, created_at, parent_id, depth
            FROM descendants
            WHERE kind = 'proof_skeleton'
            ORDER BY depth DESC, created_at DESC, node_id DESC
            LIMIT ?
            """,
            (proposition_id, limit),
        ).fetchall()
    finally:
        con.close()
    return [dict(row) for row in rows]
