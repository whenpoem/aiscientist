"""Failure ledger tools: record, FTS match, contradiction surfacing."""

from __future__ import annotations

from memory_mcp.db import _connect, tx

from ._common import _emit_event, _fts_query, _rows_to_dicts


def _signature(trigger: str, symptom: str, root_cause: str, resolution: str) -> str:
    parts = [trigger, symptom, root_cause, resolution]
    return " | ".join(part.strip().lower() for part in parts if part and part.strip())


def _recent_failures(con, limit: int = 25) -> list[dict]:
    rows = con.execute(
        """
        SELECT failure_id, trigger, symptom, root_cause, resolution, signature,
               seen_count, first_seen, last_seen
        FROM mem_failures
        ORDER BY last_seen DESC, failure_id DESC
        LIMIT ?
        """,
        (max(1, limit),),
    ).fetchall()
    return _rows_to_dicts(rows)


def _find_contradictions(con) -> list[dict]:
    explicit_rows = con.execute(
        """
        SELECT e.edge_id, e.src, src.kind AS src_kind, src.text AS src_text, src.state AS src_state,
               e.dst, dst.kind AS dst_kind, dst.text AS dst_text, dst.state AS dst_state,
               e.rationale, e.created_at
        FROM mem_edges e
        JOIN mem_nodes src ON src.node_id = e.src
        JOIN mem_nodes dst ON dst.node_id = e.dst
        WHERE e.relation = 'contradicts'
        ORDER BY e.created_at DESC, e.edge_id DESC
        """
    ).fetchall()
    evidence_rows = con.execute(
        """
        SELECT n.node_id, n.kind, n.text, n.state,
               SUM(CASE WHEN e.relation = 'supports' THEN 1 ELSE 0 END) AS support_count,
               SUM(CASE WHEN e.relation = 'refutes' THEN 1 ELSE 0 END) AS refute_count,
               MAX(e.created_at) AS last_edge_at
        FROM mem_nodes n
        JOIN mem_edges e ON e.dst = n.node_id
        JOIN mem_nodes ev ON ev.node_id = e.src
        WHERE e.relation IN ('supports', 'refutes')
          AND ev.kind = 'evidence'
          AND ev.state = 'active'
        GROUP BY n.node_id, n.kind, n.text, n.state
        HAVING support_count > 0 AND refute_count > 0
        ORDER BY last_edge_at DESC, n.node_id DESC
        """
    ).fetchall()

    contradictions: list[dict] = []
    for row in explicit_rows:
        contradictions.append(
            {
                "type": "explicit_edge",
                "edge_id": row["edge_id"],
                "src_id": row["src"],
                "src_kind": row["src_kind"],
                "src_text": row["src_text"],
                "src_state": row["src_state"],
                "dst_id": row["dst"],
                "dst_kind": row["dst_kind"],
                "dst_text": row["dst_text"],
                "dst_state": row["dst_state"],
                "rationale": row["rationale"] or "",
                "created_at": row["created_at"],
            }
        )

    for row in evidence_rows:
        evidence = con.execute(
            """
            SELECT ev.node_id, ev.text, e.relation, e.created_at
            FROM mem_edges e
            JOIN mem_nodes ev ON ev.node_id = e.src
            WHERE e.dst = ?
              AND e.relation IN ('supports', 'refutes')
              AND ev.kind = 'evidence'
              AND ev.state = 'active'
            ORDER BY e.created_at DESC, ev.node_id DESC
            LIMIT 8
            """,
            (row["node_id"],),
        ).fetchall()
        contradictions.append(
            {
                "type": "evidence_conflict",
                "node_id": row["node_id"],
                "kind": row["kind"],
                "text": row["text"],
                "state": row["state"],
                "support_count": int(row["support_count"]),
                "refute_count": int(row["refute_count"]),
                "evidence": _rows_to_dicts(evidence),
                "created_at": row["last_edge_at"],
            }
        )

    return contradictions


def record_failure(trigger: str, symptom: str, root_cause: str = "", resolution: str = "") -> dict:
    """Store a failure signature for later matching."""
    signature = _signature(trigger, symptom, root_cause, resolution)
    with tx() as con:
        cur = con.execute(
            """
            INSERT INTO mem_failures(
              trigger, symptom, root_cause, resolution, signature,
              seen_count, first_seen, last_seen
            )
            VALUES(?,?,?,?,?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            """,
            (trigger, symptom, root_cause, resolution, signature),
        )
        failure_id = int(cur.lastrowid)
        _emit_event(
            con,
            "failure_added",
            {"failure_id": failure_id, "trigger": trigger, "symptom": symptom},
        )
    return {"failure_id": failure_id}


def match_signatures(situation: str, k: int = 5) -> list[dict]:
    """FTS search prior failures ranked by BM25 relevance."""
    query = _fts_query(situation)
    if not query:
        return []
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT f.failure_id, f.trigger, f.symptom, f.root_cause, f.resolution,
                   f.signature, f.seen_count, f.first_seen, f.last_seen,
                   bm25(mem_failures_fts) AS bm25_score
            FROM mem_failures f
            JOIN mem_failures_fts ON mem_failures_fts.rowid = f.failure_id
            WHERE mem_failures_fts MATCH ?
            ORDER BY bm25_score
            LIMIT ?
            """,
            (query, max(1, k)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def find_contradictions() -> list[dict]:
    """Return places where the graph contains explicit or evidence-level conflicts."""
    con = _connect()
    try:
        return _find_contradictions(con)
    finally:
        con.close()
