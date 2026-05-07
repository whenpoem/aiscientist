"""Corpus ingestion + browsing tools (P2)."""

from __future__ import annotations

import json
from typing import Any

from prove_mcp.db import _connect, tx
from prove_mcp.embedding import EmbeddingBackend, get_embedder

from ._common import _emit_event, _normalize_keywords, encode_vector

VALID_SOURCES = {"stateval", "manual", "arxiv"}
VALID_KIND = {"lexical", "semantic"}


def _validate_problem(p: dict[str, Any]) -> tuple[str, str, str, list[str], list[str], list[str]]:
    pid = (p.get("problem_id") or "").strip()
    if not pid:
        raise ValueError("problem entries must include a non-empty 'problem_id'")
    statement = (p.get("statement") or "").strip()
    if not statement:
        raise ValueError(f"problem {pid!r} missing 'statement'")
    reference_proof = (p.get("reference_proof") or "").strip()
    lex = _normalize_keywords(p.get("lexical_keywords") or [])
    sem = _normalize_keywords(p.get("semantic_keywords") or [])
    if not lex and not sem:
        raise ValueError(
            f"problem {pid!r} must include at least one lexical or semantic keyword"
        )
    domain_tags = [str(tag).strip() for tag in (p.get("domain_tags") or []) if str(tag).strip()]
    return pid, statement, reference_proof, lex, sem, domain_tags


def _embed_keywords(
    backend: EmbeddingBackend,
    lex: list[str],
    sem: list[str],
) -> tuple[list[list[float]], list[list[float]]]:
    """Embed lexical+semantic keyword lists in a single backend call."""
    combined = lex + sem
    if not combined:
        return [], []
    vectors = backend.embed(combined)
    if len(vectors) != len(combined):
        raise RuntimeError(
            f"embedding backend {backend.name!r} returned {len(vectors)} vectors "
            f"for {len(combined)} inputs"
        )
    return vectors[: len(lex)], vectors[len(lex) :]


def ingest_proof_corpus(source: str, problems: list[dict[str, Any]]) -> dict[str, Any]:
    """Ingest a batch of proof corpus problems.

    Each ``problem`` must include ``problem_id`` and ``statement`` plus at
    least one of ``lexical_keywords`` / ``semantic_keywords``. Optional
    fields: ``reference_proof``, ``domain_tags``. Re-ingesting an existing
    ``problem_id`` replaces its row and keyword set (idempotent upsert).

    Keywords are vectorised through the active embedding backend
    (RESEARCH_AGENT_EMBED_BACKEND env). Each keyword row records the
    backend name and dim so cross-backend retrieval can be safely
    rejected.

    Returns ``{"ingested": int, "replaced": int, "backend": str, "dim": int}``.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be in {sorted(VALID_SOURCES)}; got {source!r}")
    if not isinstance(problems, list) or not problems:
        raise ValueError("problems must be a non-empty list")

    backend = get_embedder()
    backend_name = backend.name
    backend_dim = backend.dim

    ingested = 0
    replaced = 0
    with tx() as con:
        for raw in problems:
            if not isinstance(raw, dict):
                raise ValueError("each problem must be a dict")
            pid, statement, ref_proof, lex, sem, domain_tags = _validate_problem(raw)
            existing = con.execute(
                "SELECT problem_id FROM prv_corpus_problems WHERE problem_id = ?",
                (pid,),
            ).fetchone()
            if existing is not None:
                con.execute(
                    "DELETE FROM prv_corpus_keywords WHERE problem_id = ?",
                    (pid,),
                )
                con.execute(
                    """
                    UPDATE prv_corpus_problems
                    SET source = ?, statement = ?, reference_proof = ?,
                        domain_tags = ?, ingested_at = CURRENT_TIMESTAMP
                    WHERE problem_id = ?
                    """,
                    (source, statement, ref_proof, json.dumps(domain_tags), pid),
                )
                replaced += 1
            else:
                con.execute(
                    """
                    INSERT INTO prv_corpus_problems(
                      problem_id, source, statement, reference_proof, domain_tags
                    ) VALUES(?,?,?,?,?)
                    """,
                    (pid, source, statement, ref_proof, json.dumps(domain_tags)),
                )
                ingested += 1

            lex_vecs, sem_vecs = _embed_keywords(backend, lex, sem)
            for kw, vec in zip(lex, lex_vecs):
                con.execute(
                    """
                    INSERT INTO prv_corpus_keywords(
                      problem_id, keyword, kind, embedding, embed_backend, embed_dim
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (pid, kw, "lexical", encode_vector(vec), backend_name, backend_dim),
                )
            for kw, vec in zip(sem, sem_vecs):
                con.execute(
                    """
                    INSERT INTO prv_corpus_keywords(
                      problem_id, keyword, kind, embedding, embed_backend, embed_dim
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (pid, kw, "semantic", encode_vector(vec), backend_name, backend_dim),
                )
            _emit_event(
                con,
                "proof_corpus_ingested",
                {
                    "problem_id": pid,
                    "source": source,
                    "n_lexical": len(lex),
                    "n_semantic": len(sem),
                    "embed_backend": backend_name,
                },
            )

    return {
        "ingested": ingested,
        "replaced": replaced,
        "backend": backend_name,
        "dim": backend_dim,
    }


def list_corpus(source: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Browse the proof corpus.

    Returns one dict per problem with the statement, reference proof,
    domain tags, and aggregated keyword counts. Pass ``source`` to filter
    to a single ingest source.
    """
    if source is not None and source not in VALID_SOURCES:
        raise ValueError(f"source filter must be in {sorted(VALID_SOURCES)}; got {source!r}")
    limit = max(1, min(int(limit), 500))
    con = _connect()
    try:
        if source is None:
            rows = con.execute(
                """
                SELECT p.problem_id, p.source, p.statement, p.reference_proof,
                       p.domain_tags, p.ingested_at,
                       SUM(CASE WHEN k.kind = 'lexical' THEN 1 ELSE 0 END) AS n_lexical,
                       SUM(CASE WHEN k.kind = 'semantic' THEN 1 ELSE 0 END) AS n_semantic
                FROM prv_corpus_problems p
                LEFT JOIN prv_corpus_keywords k ON k.problem_id = p.problem_id
                GROUP BY p.problem_id
                ORDER BY p.ingested_at DESC, p.problem_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT p.problem_id, p.source, p.statement, p.reference_proof,
                       p.domain_tags, p.ingested_at,
                       SUM(CASE WHEN k.kind = 'lexical' THEN 1 ELSE 0 END) AS n_lexical,
                       SUM(CASE WHEN k.kind = 'semantic' THEN 1 ELSE 0 END) AS n_semantic
                FROM prv_corpus_problems p
                LEFT JOIN prv_corpus_keywords k ON k.problem_id = p.problem_id
                WHERE p.source = ?
                GROUP BY p.problem_id
                ORDER BY p.ingested_at DESC, p.problem_id ASC
                LIMIT ?
                """,
                (source, limit),
            ).fetchall()
    finally:
        con.close()

    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            tags = json.loads(row["domain_tags"] or "[]")
        except (TypeError, ValueError):
            tags = []
        out.append(
            {
                "problem_id": row["problem_id"],
                "source": row["source"],
                "statement": row["statement"],
                "reference_proof": row["reference_proof"],
                "domain_tags": tags,
                "ingested_at": row["ingested_at"],
                "n_lexical": int(row["n_lexical"] or 0),
                "n_semantic": int(row["n_semantic"] or 0),
            }
        )
    return out
