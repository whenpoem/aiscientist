"""Tool implementations for memory_mcp."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from .db import _connect, bootstrap, tx

TOOL_NAMES = [
    "propose_hypothesis",
    "attach_evidence",
    "mark_refuted",
    "get_active_frontier",
    "get_ancestors",
    "record_failure",
    "match_signatures",
    "find_contradictions",
    "snapshot",
    "ingest_paper",
    "query_literature",
    "find_baselines_for",
]

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def _node_id(kind: str) -> str:
    prefix = {
        "hypothesis": "hyp",
        "evidence": "ev",
        "question": "q",
        "experiment": "exp",
        "conclusion": "con",
    }.get(kind, "node")
    return f"{prefix}_{uuid4().hex[:12]}"


def _signature(trigger: str, symptom: str, root_cause: str, resolution: str) -> str:
    parts = [trigger, symptom, root_cause, resolution]
    return " | ".join(part.strip().lower() for part in parts if part and part.strip())


def _fts_query(text: str) -> str:
    tokens = [token.lower() for token in _TOKEN_RE.findall(text)]
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens[:12])


def _emit_event(con, kind: str, payload: dict) -> None:
    try:
        con.execute(
            "INSERT INTO cockpit_events(kind, payload, created_at) VALUES(?,?,?)",
            (kind, json.dumps(payload, ensure_ascii=True), datetime.now(timezone.utc).isoformat()),
        )
    except sqlite3.Error:
        return


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def _graph_snapshot(con) -> tuple[list[dict], list[dict]]:
    nodes = con.execute(
        """
        SELECT node_id, kind, text, state, created_at, created_by, parent_id
        FROM mem_nodes
        ORDER BY created_at ASC, node_id ASC
        """
    ).fetchall()
    edges = con.execute(
        """
        SELECT edge_id, src, dst, relation, rationale, created_at
        FROM mem_edges
        ORDER BY created_at ASC, edge_id ASC
        """
    ).fetchall()
    return _rows_to_dicts(nodes), _rows_to_dicts(edges)


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
        if parent_id:
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
    """Return active question and hypothesis nodes ordered by recency."""
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT node_id, kind, text, state, created_at, created_by, parent_id
            FROM mem_nodes
            WHERE state = 'active' AND kind IN ('question', 'hypothesis')
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
                SELECT node_id, kind, text, state, created_at, created_by, parent_id
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


def snapshot(label: str = "") -> dict:
    """Persist a point-in-time snapshot of the graph, failures, and contradiction summary."""
    snapshot_id = f"snap_{uuid4().hex[:12]}"
    with tx() as con:
        nodes, edges = _graph_snapshot(con)
        frontier = _rows_to_dicts(
            con.execute(
                """
                SELECT node_id, kind, text, state, created_at, created_by, parent_id
                FROM mem_nodes
                WHERE state = 'active' AND kind IN ('question', 'hypothesis')
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
        )
        contradictions = _find_contradictions(con)
        failures = _recent_failures(con)
        paper_count = int(con.execute("SELECT COUNT(*) FROM mem_lit_compressed").fetchone()[0])
        payload = {
            "nodes": nodes,
            "edges": edges,
            "active_frontier": frontier,
            "contradictions": contradictions,
            "recent_failures": failures,
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "active_frontier": len(frontier),
                "contradictions": len(contradictions),
                "recent_failures": len(failures),
                "papers": paper_count,
            },
        }
        con.execute(
            "INSERT INTO mem_snapshots(snapshot_id, label, payload) VALUES(?,?,?)",
            (snapshot_id, label, json.dumps(payload, ensure_ascii=True)),
        )
        _emit_event(
            con,
            "snapshot_created",
            {"snapshot_id": snapshot_id, "label": label, "counts": payload["counts"]},
        )
    return {"snapshot_id": snapshot_id, "label": label, "counts": payload["counts"]}


def ingest_paper(paper_id: str, source: str, structured: dict) -> dict:
    """Store a compressed paper produced by the librarian."""
    if source not in {"arxiv", "openalex", "manual"}:
        raise ValueError("source must be one of: arxiv, openalex, manual")
    authors = structured.get("authors", [])
    relates_to = structured.get("relates_to", {})
    with tx() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO mem_lit_compressed(
              paper_id, source, title, authors, year, venue, problem, method,
              claimed_results, assumptions, limitations, trust_level, relates_to,
              raw_abstract, ingested_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """,
            (
                paper_id,
                source,
                structured.get("title", ""),
                json.dumps(authors, ensure_ascii=True),
                structured.get("year"),
                structured.get("venue", ""),
                structured.get("problem", ""),
                structured.get("method", ""),
                structured.get("claimed_results", ""),
                structured.get("assumptions", ""),
                structured.get("limitations", ""),
                structured.get("trust_level", 0.5),
                json.dumps(relates_to, ensure_ascii=True),
                structured.get("raw_abstract", ""),
            ),
        )
    return {"ingested": paper_id}


def query_literature(question: str, k: int = 10) -> list[dict]:
    """Return literature ranked by BM25 and trust level."""
    query = _fts_query(question)
    con = _connect()
    try:
        if not query:
            rows = con.execute(
                """
                SELECT paper_id, title, problem, method, claimed_results,
                       assumptions, limitations, trust_level, 0.0 AS bm25_score
                FROM mem_lit_compressed
                ORDER BY trust_level DESC, ingested_at DESC
                LIMIT ?
                """,
                (max(1, k),),
            ).fetchall()
            return [dict(row) for row in rows]
        rows = con.execute(
            """
            SELECT p.paper_id, p.title, p.problem, p.method, p.claimed_results,
                   p.assumptions, p.limitations, p.trust_level,
                   bm25(mem_lit_fts) AS bm25_score
            FROM mem_lit_compressed p
            JOIN mem_lit_fts ON mem_lit_fts.rowid = p.rowid
            WHERE mem_lit_fts MATCH ?
            ORDER BY bm25_score * (1.0 / (0.5 + p.trust_level))
            LIMIT ?
            """,
            (query, max(1, k)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def find_baselines_for(method_description: str, k: int = 5) -> list[dict]:
    """Return papers whose method descriptions best match the given method."""
    return query_literature(method_description, k=k)


bootstrap()
