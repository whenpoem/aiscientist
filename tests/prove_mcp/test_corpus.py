"""Corpus ingestion + browse tests (P2)."""

from __future__ import annotations

import pytest


def _problem(pid: str, statement: str, lex=None, sem=None, **extra):
    return {
        "problem_id": pid,
        "statement": statement,
        "lexical_keywords": lex or [],
        "semantic_keywords": sem or [],
        **extra,
    }


def test_ingest_writes_problem_and_keyword_rows(workspace):
    impl = workspace["prove_mcp.impl"]
    db = workspace["prove_mcp.db"]

    result = impl.ingest_proof_corpus(
        "manual",
        [
            _problem(
                "p1",
                "Sample mean is an unbiased estimator of the population mean",
                lex=["sample", "mean", "unbiased"],
                sem=["estimator unbiasedness"],
                reference_proof="Apply linearity of expectation.",
                domain_tags=["estimation"],
            )
        ],
    )
    assert result["ingested"] == 1
    assert result["replaced"] == 0
    assert result["backend"] == "mock"

    con = db._connect()
    try:
        prob = con.execute(
            "SELECT problem_id, source, statement, reference_proof, domain_tags "
            "FROM prv_corpus_problems WHERE problem_id = 'p1'"
        ).fetchone()
        kws = con.execute(
            "SELECT keyword, kind, embed_backend FROM prv_corpus_keywords "
            "WHERE problem_id = 'p1' ORDER BY kind, keyword"
        ).fetchall()
    finally:
        con.close()

    assert prob["statement"].startswith("Sample mean")
    assert prob["reference_proof"] == "Apply linearity of expectation."
    assert prob["domain_tags"] == '["estimation"]'

    keywords = {(row["keyword"], row["kind"]) for row in kws}
    assert ("sample", "lexical") in keywords
    assert ("mean", "lexical") in keywords
    assert ("unbiased", "lexical") in keywords
    assert ("estimator unbiasedness", "semantic") in keywords
    assert all(row["embed_backend"] == "mock" for row in kws)


def test_ingest_is_idempotent_via_upsert(workspace):
    impl = workspace["prove_mcp.impl"]
    db = workspace["prove_mcp.db"]

    impl.ingest_proof_corpus(
        "manual",
        [_problem("p1", "Sample mean unbiased", lex=["sample", "mean"])],
    )
    second = impl.ingest_proof_corpus(
        "manual",
        [_problem("p1", "Sample mean is unbiased (revised)", lex=["mean"])],
    )

    assert second["replaced"] == 1
    assert second["ingested"] == 0

    con = db._connect()
    try:
        prob = con.execute(
            "SELECT statement FROM prv_corpus_problems WHERE problem_id = 'p1'"
        ).fetchone()
        kws = con.execute(
            "SELECT keyword FROM prv_corpus_keywords WHERE problem_id = 'p1'"
        ).fetchall()
    finally:
        con.close()
    assert prob["statement"] == "Sample mean is unbiased (revised)"
    assert {row["keyword"] for row in kws} == {"mean"}


def test_ingest_rejects_invalid_source(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="source must be in"):
        impl.ingest_proof_corpus("from-nowhere", [_problem("p", "x", lex=["a"])])


def test_ingest_rejects_problem_with_no_keywords(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="keyword"):
        impl.ingest_proof_corpus("manual", [_problem("pX", "statement only")])


def test_ingest_rejects_missing_statement(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="statement"):
        impl.ingest_proof_corpus(
            "manual",
            [{"problem_id": "p1", "lexical_keywords": ["a"]}],
        )


def test_ingest_rejects_missing_problem_id(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError, match="problem_id"):
        impl.ingest_proof_corpus(
            "manual",
            [{"statement": "ok", "lexical_keywords": ["a"]}],
        )


def test_list_corpus_returns_summaries(workspace):
    impl = workspace["prove_mcp.impl"]
    impl.ingest_proof_corpus(
        "manual",
        [
            _problem("p1", "first statement", lex=["alpha", "beta"], sem=["combo a"]),
            _problem("p2", "second statement", lex=["gamma"]),
        ],
    )
    rows = impl.list_corpus()
    by_id = {row["problem_id"]: row for row in rows}
    assert set(by_id) == {"p1", "p2"}
    assert by_id["p1"]["n_lexical"] == 2
    assert by_id["p1"]["n_semantic"] == 1
    assert by_id["p2"]["n_lexical"] == 1
    assert by_id["p2"]["n_semantic"] == 0


def test_list_corpus_filters_by_source(workspace):
    impl = workspace["prove_mcp.impl"]
    impl.ingest_proof_corpus(
        "manual",
        [_problem("manual_p", "manual stmt", lex=["a"])],
    )
    impl.ingest_proof_corpus(
        "stateval",
        [_problem("stateval_p", "stateval stmt", lex=["b"])],
    )

    manual = {row["problem_id"] for row in impl.list_corpus(source="manual")}
    stateval = {row["problem_id"] for row in impl.list_corpus(source="stateval")}
    assert manual == {"manual_p"}
    assert stateval == {"stateval_p"}


def test_list_corpus_rejects_invalid_source_filter(workspace):
    impl = workspace["prove_mcp.impl"]
    with pytest.raises(ValueError):
        impl.list_corpus(source="cosmic")
