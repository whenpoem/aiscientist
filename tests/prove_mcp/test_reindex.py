"""Reindex pathway tests (v4.2.0a0 / ADR 0010)."""

from __future__ import annotations


def _problem(pid: str, statement: str, lex=None, sem=None, **extra):
    return {
        "problem_id": pid,
        "statement": statement,
        "lexical_keywords": lex or [],
        "semantic_keywords": sem or [],
        **extra,
    }


def test_reindex_is_idempotent_under_unchanged_backend(workspace):
    """Running reindex twice with no backend change produces the same
    metadata triple and the same row count."""
    impl = workspace["prove_mcp.impl"]
    db = workspace["prove_mcp.db"]

    impl.ingest_proof_corpus(
        "manual",
        [
            _problem("p1", "stmt", lex=["a", "b"], sem=["c"]),
            _problem("p2", "stmt2", lex=["d"], sem=[]),
        ],
    )

    first = impl.reindex_corpus()
    assert first["reindexed"] == 2
    assert first["skipped"] == 0
    assert first["total"] == 2

    second = impl.reindex_corpus()
    assert second["reindexed"] == 2
    assert second["skipped"] == 0

    con = db._connect()
    try:
        rows = con.execute(
            "SELECT COUNT(*) AS n FROM prv_corpus_keywords"
        ).fetchone()
    finally:
        con.close()
    # Three lex + one sem from p1 + p2 → 4 rows survive both passes.
    assert int(rows["n"]) == 4


def test_reindex_rewrites_mismatched_rows(workspace, monkeypatch):
    """After flipping the active model, reindex restores the active triple."""
    impl = workspace["prove_mcp.impl"]
    db = workspace["prove_mcp.db"]

    impl.ingest_proof_corpus(
        "manual",
        [_problem("p1", "stmt", lex=["alpha"], sem=["beta combo"])],
    )

    # Simulate a model upgrade by patching the active backend to report a
    # different model_name. Same backend / dim → only the model differs.
    fake_embedding = workspace["prove_mcp.embedding"]
    fake_corpus = workspace["prove_mcp.tools.corpus"]
    dim = fake_embedding.MOCK_DIM

    class _Upgraded(fake_embedding.MockEmbedder):
        def __init__(self):
            super().__init__(dim=dim)
            self.model_name = "mock-upgraded-v2"

    monkeypatch.setattr(fake_embedding, "get_embedder", lambda: _Upgraded())
    monkeypatch.setattr(fake_corpus, "get_embedder", lambda: _Upgraded())

    result = impl.reindex_corpus()
    assert result["reindexed"] == 1
    assert result["model"] == "mock-upgraded-v2"

    con = db._connect()
    try:
        rows = con.execute(
            "SELECT DISTINCT embedding_model FROM prv_corpus_keywords"
        ).fetchall()
    finally:
        con.close()
    assert {row["embedding_model"] for row in rows} == {"mock-upgraded-v2"}


def test_reindex_empty_corpus_is_no_op(workspace):
    impl = workspace["prove_mcp.impl"]
    result = impl.reindex_corpus()
    assert result["total"] == 0
    assert result["reindexed"] == 0
    assert result["skipped"] == 0


def test_corpus_backend_signatures_after_simulated_upgrade(workspace, monkeypatch):
    """When two triples coexist (e.g. legacy + just-ingested), the helper
    returns one row per triple."""
    impl = workspace["prove_mcp.impl"]
    db = workspace["prove_mcp.db"]

    impl.ingest_proof_corpus(
        "manual",
        [_problem("p1", "stmt", lex=["alpha"])],
    )
    # Manually inject a second row with a different model identifier to
    # simulate a legacy v4.1 row carrying the default 'unknown' model.
    con = db._connect()
    try:
        con.execute(
            """
            INSERT INTO prv_corpus_keywords(
              problem_id, keyword, kind, embedding,
              embed_backend, embed_dim, embedding_model
            ) VALUES('p1', 'legacy', 'lexical', x'00', 'mock', 64, 'unknown')
            """
        )
        con.commit()
    finally:
        con.close()

    sigs = impl.corpus_backend_signatures()
    models = {sig["embedding_model"] for sig in sigs}
    assert "unknown" in models
    assert any(m.startswith("mock-dim") for m in models)


def test_reindex_dry_run_does_not_probe_active_backend(
    workspace, monkeypatch, tmp_path
):
    """Dry-run must stay cheap: it can compare stored signatures without
    asking the active backend for dim, which may download a model or call
    a remote API."""
    impl = workspace["prove_mcp.impl"]
    impl.ingest_proof_corpus(
        "manual",
        [_problem("p1", "stmt", lex=["alpha"])],
    )

    import importlib.util
    from pathlib import Path

    import prove_mcp.embedding as embedding

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "reindex_proof_corpus.py"
    spec = importlib.util.spec_from_file_location("reindex_proof_corpus_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    reindex_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reindex_script)

    class _RemoteLike:
        name = "openai"
        model_name = "text-embedding-3-large"

        @property
        def dim(self):
            raise AssertionError("dry-run should not probe backend.dim")

    monkeypatch.setattr(embedding, "get_embedder", lambda: _RemoteLike())

    from io import StringIO

    out = StringIO()
    result = reindex_script.run(dry_run=True, out=out)

    assert result["dry_run"] is True
    assert "dry-run:" in out.getvalue()
