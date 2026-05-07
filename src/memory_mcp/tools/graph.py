"""Hypothesis graph tools: propose, attach, refute, frontier, ancestors."""

from __future__ import annotations

from memory_mcp.db import _connect, tx

from ._common import _emit_event, _node_id


def propose_hypothesis(text: str, parent_id: str | None = None, rationale: str = "") -> dict:
    """Create a new hypothesis node and optionally connect it to a parent."""
    node_id = _node_id("hypothesis")
    with tx() as con:
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
            VALUES(?,?,?,?,?,?)
            """,
            (node_id, "hypothesis", text, "active", "claude", parent_id),
        )
        con.execute("INSERT OR IGNORE INTO mem_bt_ratings(node_id) VALUES(?)", (node_id,))
        if parent_id:
            con.execute(
                "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
                (parent_id, node_id, "parent_of", rationale),
            )
            con.execute(
                "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
                (parent_id, node_id, "refines", rationale),
            )
        _emit_event(con, "graph_delta", {"node_id": node_id, "kind": "hypothesis", "text": text})
    return {"node_id": node_id}


def attach_evidence(node_id: str, evidence_text: str, polarity: str) -> dict:
    """Create an evidence node and connect it to a target hypothesis."""
    if polarity not in {"supports", "refutes"}:
        raise ValueError("polarity must be one of: supports, refutes")
    evidence_id = _node_id("evidence")
    with tx() as con:
        target = con.execute(
            "SELECT node_id FROM mem_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if target is None:
            raise ValueError(f"Unknown node: {node_id}")
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by, parent_id)
            VALUES(?,?,?,?,?,?)
            """,
            (evidence_id, "evidence", evidence_text, "active", "claude", node_id),
        )
        con.execute(
            "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
            (node_id, evidence_id, "parent_of", evidence_text),
        )
        con.execute(
            "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
            (evidence_id, node_id, polarity, evidence_text),
        )
        _emit_event(
            con,
            "graph_delta",
            {"node_id": evidence_id, "kind": "evidence", "text": evidence_text},
        )
    return {"evidence_id": evidence_id}


def mark_refuted(node_id: str, reason: str, evidence_ids: list[str] | None = None) -> dict:
    """Mark an existing node as refuted."""
    with tx() as con:
        cur = con.execute(
            "UPDATE mem_nodes SET state = 'refuted' WHERE node_id = ?",
            (node_id,),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown node: {node_id}")
        _emit_event(
            con,
            "graph_delta",
            {
                "node_id": node_id,
                "kind": "refuted",
                "text": reason,
                "evidence_ids": evidence_ids or [],
            },
        )
    return {"node_id": node_id, "state": "refuted"}


def get_active_frontier() -> list[dict]:
    """Return active question, hypothesis, and proposition nodes by recency.

    Propositions (proof-trunk peers of hypotheses, see architecture.md §13)
    are surfaced on the frontier so the main model treats them on equal
    footing during planning. Skeletons and snippets are intentionally
    omitted — they are too granular for the frontier view; query them
    directly via mem_nodes when needed.
    """
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
            FROM mem_nodes
            WHERE state = 'active'
              AND kind IN ('question', 'hypothesis', 'proposition')
            ORDER BY created_at DESC
            LIMIT 50
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def get_ancestors(node_id: str) -> list[dict]:
    """Return a node plus its ancestors up to the root."""
    con = _connect()
    try:
        chain: list[dict] = []
        current = node_id
        while current:
            row = con.execute(
                """
                SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
                FROM mem_nodes
                WHERE node_id = ?
                """,
                (current,),
            ).fetchone()
            if row is None:
                break
            item = dict(row)
            chain.append(item)
            current = item["parent_id"]
        return chain
    finally:
        con.close()
