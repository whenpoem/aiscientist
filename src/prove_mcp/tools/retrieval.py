"""Bidirectional max-matching retrieval (P2).

Implements the StatProver-style similarity score described in
architecture.md §13:

    Sim(A→B) = mean over kw a in A of max over kw b in B of cos(emb_a, emb_b)
    S(A,B)   = (Sim(A→B) + Sim(B→A)) / 2

The asymmetric direction averaging rewards strong local matches over
generic terminology overlap. Public surface is a single tool,
``retrieve_skeletons``, which the main agent calls after extracting
keywords from the query proposition (per ADR 0007 — keyword extraction
is the agent's job, vector math is the tool's job).
"""

from __future__ import annotations

from typing import Any

from prove_mcp.db import _connect
from prove_mcp.embedding import cosine, get_embedder

from ._common import _normalize_keywords, decode_vector


def _direction_score(src_vecs: list[list[float]], dst_vecs: list[list[float]]) -> float:
    if not src_vecs or not dst_vecs:
        return 0.0
    total = 0.0
    for src in src_vecs:
        best = max(cosine(src, dst) for dst in dst_vecs)
        total += best
    return total / len(src_vecs)


def retrieve_skeletons(
    proposition_text: str,
    lexical_keywords: list[str] | None = None,
    semantic_keywords: list[str] | None = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Rank corpus problems by bidirectional max-matching similarity.

    The caller is expected to have extracted ``lexical_keywords`` and
    ``semantic_keywords`` from ``proposition_text`` already (typically
    via an LLM call before invoking this tool). At least one of the two
    keyword lists must be non-empty.

    Returns up to ``k`` problems, each scored by S(A,B) and tagged with
    its ``lexical_score``, ``semantic_score`` (the two component
    direction averages), and the corpus problem's metadata. Sorted by
    overall similarity descending.

    Cross-backend retrieval is forbidden: the active embedding backend
    (RESEARCH_AGENT_EMBED_BACKEND) must match the backend the corpus was
    ingested under. A backend mismatch with no overlapping rows raises
    ``RuntimeError`` with a clear hint to re-ingest.
    """
    lex = _normalize_keywords(lexical_keywords or [])
    sem = _normalize_keywords(semantic_keywords or [])
    if not lex and not sem:
        raise ValueError(
            "retrieve_skeletons requires at least one lexical or semantic keyword"
        )
    k = max(1, min(int(k), 200))

    backend = get_embedder()
    backend_name = backend.name
    backend_dim = backend.dim

    # Embed the query keywords first so that backend mismatch surfaces as
    # a clean error, not a silent zero-result return.
    query_lex_vecs, query_sem_vecs = _split_embed(backend, lex, sem)

    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT k.problem_id, k.keyword, k.kind, k.embedding,
                   p.source, p.statement, p.reference_proof, p.domain_tags
            FROM prv_corpus_keywords k
            JOIN prv_corpus_problems p ON p.problem_id = k.problem_id
            WHERE k.embed_backend = ? AND k.embed_dim = ?
            """,
            (backend_name, backend_dim),
        ).fetchall()
        # Surface a clear hint if the corpus was ingested under a different
        # backend, instead of returning silently empty.
        if not rows:
            other = con.execute(
                """
                SELECT DISTINCT embed_backend, embed_dim
                FROM prv_corpus_keywords
                LIMIT 5
                """
            ).fetchall()
            if other:
                pairs = ", ".join(f"{r['embed_backend']}/dim={r['embed_dim']}" for r in other)
                raise RuntimeError(
                    f"corpus has no rows for backend {backend_name!r} dim={backend_dim}; "
                    f"existing rows are: {pairs}. Set RESEARCH_AGENT_EMBED_BACKEND to "
                    "match, or re-ingest under the active backend."
                )
            return []
    finally:
        con.close()

    # Group keyword vectors per problem.
    per_problem: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = row["problem_id"]
        bucket = per_problem.setdefault(
            pid,
            {
                "source": row["source"],
                "statement": row["statement"],
                "reference_proof": row["reference_proof"],
                "domain_tags_raw": row["domain_tags"] or "[]",
                "lex": [],
                "sem": [],
            },
        )
        vec = decode_vector(row["embedding"], backend_dim)
        if row["kind"] == "lexical":
            bucket["lex"].append(vec)
        else:
            bucket["sem"].append(vec)

    scored: list[dict[str, Any]] = []
    for pid, bucket in per_problem.items():
        lex_score = _bidirectional(query_lex_vecs, bucket["lex"])
        sem_score = _bidirectional(query_sem_vecs, bucket["sem"])
        # When one side has no vectors on either query or corpus, fall back
        # to the other side rather than dragging the score to zero.
        if lex_score is None and sem_score is None:
            continue
        if lex_score is None:
            similarity = sem_score
        elif sem_score is None:
            similarity = lex_score
        else:
            similarity = 0.5 * (lex_score + sem_score)
        scored.append(
            {
                "problem_id": pid,
                "source": bucket["source"],
                "statement": bucket["statement"],
                "reference_proof": bucket["reference_proof"],
                "domain_tags_raw": bucket["domain_tags_raw"],
                "lexical_score": None if lex_score is None else round(lex_score, 6),
                "semantic_score": None if sem_score is None else round(sem_score, 6),
                "similarity": round(similarity, 6),
            }
        )

    scored.sort(
        key=lambda r: (r["similarity"], r["problem_id"]),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    import json

    for row in scored[:k]:
        try:
            tags = json.loads(row.pop("domain_tags_raw"))
        except (TypeError, ValueError):
            row.pop("domain_tags_raw", None)
            tags = []
        row["domain_tags"] = tags
        out.append(row)
    return out


def _split_embed(backend, lex: list[str], sem: list[str]):
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


def _bidirectional(query_vecs: list[list[float]], corpus_vecs: list[list[float]]) -> float | None:
    """Average S(query, corpus) and S(corpus, query). Returns None when
    either side has no vectors so the caller can fall back to the other
    keyword kind cleanly."""
    if not query_vecs or not corpus_vecs:
        return None
    forward = _direction_score(query_vecs, corpus_vecs)
    backward = _direction_score(corpus_vecs, query_vecs)
    return 0.5 * (forward + backward)
