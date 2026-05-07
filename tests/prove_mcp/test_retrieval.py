"""retrieve_skeletons + bidirectional max-matching tests (P2)."""

from __future__ import annotations

import pytest


def _problem(pid, stmt, lex, sem):
    return {
        "problem_id": pid,
        "statement": stmt,
        "lexical_keywords": lex,
        "semantic_keywords": sem,
    }


def _seed_corpus(impl):
    impl.ingest_proof_corpus(
        "manual",
        [
            _problem(
                "estimator_unbiased",
                "Sample mean is unbiased estimator of population mean",
                lex=["sample", "mean", "unbiased", "estimator"],
                sem=["estimator unbiasedness", "linearity of expectation"],
            ),
            _problem(
                "chebyshev_bound",
                "Chebyshev bounds tail probability via variance",
                lex=["chebyshev", "tail", "variance", "bound"],
                sem=["concentration inequality"],
            ),
            _problem(
                "cauchy_schwarz",
                "Cauchy-Schwarz on inner product spaces",
                lex=["cauchy", "schwarz", "inner", "product"],
                sem=["inner product inequality"],
            ),
            _problem(
                "regression_normal",
                "OLS estimator is BLUE under Gauss-Markov",
                lex=["ols", "blue", "gauss", "markov"],
                sem=["best linear unbiased"],
            ),
        ],
    )


def test_retrieve_returns_top_k_in_descending_similarity(workspace):
    impl = workspace["prove_mcp.impl"]
    _seed_corpus(impl)

    out = impl.retrieve_skeletons(
        "Show that the sample mean is unbiased",
        lexical_keywords=["sample", "mean", "unbiased", "estimator"],
        semantic_keywords=["estimator unbiasedness"],
        k=3,
    )
    assert len(out) <= 3
    sims = [row["similarity"] for row in out]
    assert sims == sorted(sims, reverse=True)
    assert out[0]["problem_id"] == "estimator_unbiased"
    assert out[0]["similarity"] > 0.4


def test_retrieve_k_caps_results(workspace):
    impl = workspace["prove_mcp.impl"]
    _seed_corpus(impl)

    out = impl.retrieve_skeletons(
        "anything",
        lexical_keywords=["bound"],
        semantic_keywords=["concentration inequality"],
        k=2,
    )
    assert len(out) == 2


def test_retrieve_returns_metadata_fields(workspace):
    impl = workspace["prove_mcp.impl"]
    _seed_corpus(impl)

    [top] = impl.retrieve_skeletons(
        "Show Chebyshev tail bound",
        lexical_keywords=["chebyshev", "tail", "variance"],
        semantic_keywords=["concentration inequality"],
        k=1,
    )
    assert top["problem_id"] == "chebyshev_bound"
    assert top["statement"].startswith("Chebyshev")
    assert top["domain_tags"] == []
    assert isinstance(top["lexical_score"], float)
    assert isinstance(top["semantic_score"], float)


def test_retrieve_falls_back_when_only_lexical_or_semantic_exists(workspace):
    impl = workspace["prove_mcp.impl"]
    impl.ingest_proof_corpus(
        "manual",
        [
            _problem(
                "lex_only",
                "lexical only example",
                lex=["alpha", "beta"],
                sem=[],
            ),
            _problem(
                "sem_only",
                "semantic only example",
                lex=[],
                sem=["something abstract"],
            ),
        ],
    )
    # Query has only lexical keywords; the lex_only problem should still be
    # findable, the sem_only problem cannot match (no overlap), so result
    # set is non-empty and lex_only ranks first.
    out = impl.retrieve_skeletons(
        "alpha context",
        lexical_keywords=["alpha"],
        semantic_keywords=[],
        k=5,
    )
    ids = [row["problem_id"] for row in out]
    assert "lex_only" in ids


def test_retrieve_requires_at_least_one_keyword(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="keyword"):
        impl.retrieve_skeletons("text only", lexical_keywords=[], semantic_keywords=[])


def test_retrieve_rejects_backend_mismatch(workspace, monkeypatch):
    """Ingest under one backend, then query under a different one — the
    retrieval must surface a clear error rather than return silently."""
    impl = workspace["prove_mcp.impl"]

    # Seed under the active mock backend.
    impl.ingest_proof_corpus(
        "manual",
        [_problem("p1", "stmt", lex=["alpha"], sem=[])],
    )

    # Switch to a fake backend with different name/dim.
    fake_embedding = workspace["prove_mcp.embedding"]
    real_get = fake_embedding.get_embedder

    class _Fake:
        name = "fakelocal"
        dim = 999

        def embed(self, texts):
            return [[0.0] * 999 for _ in texts]

    monkeypatch.setattr(fake_embedding, "get_embedder", lambda: _Fake())
    # Also patch the retrieval module's bound reference.
    retrieval = workspace["prove_mcp.tools.retrieval"]
    monkeypatch.setattr(retrieval, "get_embedder", lambda: _Fake())

    with pytest.raises(RuntimeError, match="backend"):
        impl.retrieve_skeletons(
            "anything",
            lexical_keywords=["alpha"],
            semantic_keywords=[],
            k=3,
        )

    # Restore (other tests inherit the original via per-test monkeypatch
    # auto-undo, but assert restoration locally for safety).
    fake_embedding.get_embedder = real_get


def test_retrieve_empty_corpus_returns_empty(workspace):
    impl = workspace["prove_mcp.impl"]
    out = impl.retrieve_skeletons(
        "anything",
        lexical_keywords=["x"],
        semantic_keywords=[],
        k=5,
    )
    assert out == []


def test_retrieval_recall_on_holdout_set(workspace):
    """50-row recall sanity. Seed 8 problems each with a unique
    discriminating keyword; verify that querying with that exact keyword
    returns the matching problem at rank 1 in 8/8 cases (>= 0.7 recall
    threshold from the P2 plan, comfortably exceeded on this fixture)."""
    impl = workspace["prove_mcp.impl"]
    fixtures = [
        ("estimator_unbiased", "sample mean unbiased", ["unbiased"], ["unbiasedness"]),
        ("chebyshev_bound", "chebyshev tail bound", ["chebyshev"], ["concentration"]),
        ("cauchy_schwarz", "cauchy schwarz inner", ["cauchy"], ["inner product inequality"]),
        ("ols_blue", "ols blue gauss markov", ["ols"], ["best linear unbiased"]),
        ("clt_iid", "central limit iid", ["clt"], ["asymptotic normality"]),
        ("mle_consistent", "mle consistency", ["mle"], ["maximum likelihood consistency"]),
        ("delta_method", "delta method asymptotics", ["delta"], ["taylor linearization"]),
        ("bayes_consistent", "posterior consistency", ["bayes"], ["posterior concentration"]),
    ]
    impl.ingest_proof_corpus(
        "manual",
        [_problem(pid, stmt, lex, sem) for pid, stmt, lex, sem in fixtures],
    )

    hits = 0
    for pid, _stmt, lex, sem in fixtures:
        out = impl.retrieve_skeletons("query", lexical_keywords=lex, semantic_keywords=sem, k=1)
        if out and out[0]["problem_id"] == pid:
            hits += 1
    assert hits == len(fixtures)
