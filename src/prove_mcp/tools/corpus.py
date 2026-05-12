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
    backend name, the specific model identifier, and the vector
    dimension so cross-(backend, model, dim) retrieval can be safely
    rejected (ADR 0010).

    Returns ``{"ingested": int, "replaced": int, "backend": str,
    "model": str, "dim": int}``.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be in {sorted(VALID_SOURCES)}; got {source!r}")
    if not isinstance(problems, list) or not problems:
        raise ValueError("problems must be a non-empty list")

    backend = get_embedder()
    backend_name = backend.name
    backend_dim = backend.dim
    model_name = backend.model_name

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
                      problem_id, keyword, kind, embedding,
                      embed_backend, embed_dim, embedding_model
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        pid, kw, "lexical", encode_vector(vec),
                        backend_name, backend_dim, model_name,
                    ),
                )
            for kw, vec in zip(sem, sem_vecs):
                con.execute(
                    """
                    INSERT INTO prv_corpus_keywords(
                      problem_id, keyword, kind, embedding,
                      embed_backend, embed_dim, embedding_model
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        pid, kw, "semantic", encode_vector(vec),
                        backend_name, backend_dim, model_name,
                    ),
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
                    "embedding_model": model_name,
                },
            )

    return {
        "ingested": ingested,
        "replaced": replaced,
        "backend": backend_name,
        "model": model_name,
        "dim": backend_dim,
    }


def reindex_corpus(batch_size: int = 25) -> dict[str, Any]:
    """Re-embed every stored corpus problem under the active backend.

    Reads the keyword strings that are already stored in
    ``prv_corpus_keywords`` (the strings are preserved across
    ingestions; only the embedding bytes and the metadata triple change)
    and re-encodes them with the currently configured embedding
    backend. Existing keyword rows under other (backend, model, dim)
    triples are dropped per problem and replaced with fresh rows.

    Idempotent. A second call with no backend change re-encodes the
    same vectors and rewrites the same metadata; nothing breaks but
    nothing useful happens either, so the cockpit prompts the user
    only when a mismatch is detected.

    Emits ``proof_corpus_reindex_progress`` per batch so the cockpit
    can show a live progress indicator during long runs.

    Returns ``{"reindexed": int, "skipped": int, "backend": str,
    "model": str, "dim": int}``.
    """
    batch_size = max(1, min(int(batch_size), 200))
    backend = get_embedder()
    backend_name = backend.name
    backend_dim = backend.dim
    model_name = backend.model_name

    con = _connect()
    try:
        problems = con.execute(
            "SELECT problem_id FROM prv_corpus_problems ORDER BY problem_id"
        ).fetchall()
    finally:
        con.close()

    reindexed = 0
    skipped = 0
    total = len(problems)
    if total == 0:
        return {
            "reindexed": 0,
            "skipped": 0,
            "backend": backend_name,
            "model": model_name,
            "dim": backend_dim,
            "total": 0,
        }

    for batch_start in range(0, total, batch_size):
        batch_ids = [row["problem_id"] for row in problems[batch_start : batch_start + batch_size]]
        with tx() as con:
            for pid in batch_ids:
                keyword_rows = con.execute(
                    """
                    SELECT keyword, kind
                    FROM prv_corpus_keywords
                    WHERE problem_id = ?
                    ORDER BY kind, keyword
                    """,
                    (pid,),
                ).fetchall()
                if not keyword_rows:
                    skipped += 1
                    continue
                lex = [row["keyword"] for row in keyword_rows if row["kind"] == "lexical"]
                sem = [row["keyword"] for row in keyword_rows if row["kind"] == "semantic"]
                lex_vecs, sem_vecs = _embed_keywords(backend, lex, sem)
                con.execute(
                    "DELETE FROM prv_corpus_keywords WHERE problem_id = ?",
                    (pid,),
                )
                for kw, vec in zip(lex, lex_vecs):
                    con.execute(
                        """
                        INSERT INTO prv_corpus_keywords(
                          problem_id, keyword, kind, embedding,
                          embed_backend, embed_dim, embedding_model
                        ) VALUES(?,?,?,?,?,?,?)
                        """,
                        (
                            pid, kw, "lexical", encode_vector(vec),
                            backend_name, backend_dim, model_name,
                        ),
                    )
                for kw, vec in zip(sem, sem_vecs):
                    con.execute(
                        """
                        INSERT INTO prv_corpus_keywords(
                          problem_id, keyword, kind, embedding,
                          embed_backend, embed_dim, embedding_model
                        ) VALUES(?,?,?,?,?,?,?)
                        """,
                        (
                            pid, kw, "semantic", encode_vector(vec),
                            backend_name, backend_dim, model_name,
                        ),
                    )
                reindexed += 1
            _emit_event(
                con,
                "proof_corpus_reindex_progress",
                {
                    "processed": min(batch_start + batch_size, total),
                    "total": total,
                    "backend": backend_name,
                    "model": model_name,
                    "dim": backend_dim,
                },
            )

    return {
        "reindexed": reindexed,
        "skipped": skipped,
        "backend": backend_name,
        "model": model_name,
        "dim": backend_dim,
        "total": total,
    }


def corpus_backend_signatures() -> list[dict[str, Any]]:
    """Return the distinct (backend, model, dim) triples present in the corpus.

    Useful for the cockpit cold-start check: if any triple differs from
    the active backend's signature, the cockpit nudges the user toward
    ``scripts/reindex_proof_corpus.py``.
    """
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT embed_backend, embedding_model, embed_dim, COUNT(*) AS n
            FROM prv_corpus_keywords
            GROUP BY embed_backend, embedding_model, embed_dim
            ORDER BY n DESC
            """
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "embed_backend": row["embed_backend"],
            "embedding_model": row["embedding_model"],
            "embed_dim": int(row["embed_dim"]),
            "row_count": int(row["n"]),
        }
        for row in rows
    ]


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
