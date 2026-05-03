"""Literature compression tools: ingest, query, baseline lookup."""

from __future__ import annotations

import json

from memory_mcp.db import _connect, tx

from ._common import _emit_event, _fts_query


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
        _emit_event(
            con,
            "literature_ingested",
            {
                "paper_id": paper_id,
                "source": source,
                "title": structured.get("title", ""),
            },
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
