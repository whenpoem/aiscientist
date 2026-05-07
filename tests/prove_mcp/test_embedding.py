"""Embedding adapter tests (P2)."""

from __future__ import annotations

import pytest


def test_mock_embedder_is_deterministic(workspace):
    embedding = workspace["prove_mcp.embedding"]
    a = embedding.MockEmbedder().embed(["sample mean unbiased"])
    b = embedding.MockEmbedder().embed(["sample mean unbiased"])
    assert a == b


def test_mock_embedder_token_overlap_increases_similarity(workspace):
    embedding = workspace["prove_mcp.embedding"]
    enc = embedding.MockEmbedder()
    near = enc.embed(["sample mean unbiased estimator"])
    same = enc.embed(["sample mean unbiased"])
    far = enc.embed(["unrelated cuda kernel optimization"])

    near_sim = embedding.cosine(same[0], near[0])
    far_sim = embedding.cosine(same[0], far[0])
    assert near_sim > far_sim
    assert near_sim > 0.4
    assert far_sim < 0.2


def test_mock_embedder_returns_unit_vectors(workspace):
    embedding = workspace["prove_mcp.embedding"]
    [vec] = embedding.MockEmbedder().embed(["non empty text"])
    norm = sum(v * v for v in vec) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_get_embedder_factory_respects_env(workspace, monkeypatch):
    embedding = workspace["prove_mcp.embedding"]

    monkeypatch.setenv(embedding.ENV_BACKEND, "mock")
    assert embedding.get_embedder().name == "mock"

    monkeypatch.setenv(embedding.ENV_BACKEND, "MoCk")  # case-insensitive
    assert embedding.get_embedder().name == "mock"

    monkeypatch.setenv(embedding.ENV_BACKEND, "weird")
    with pytest.raises(ValueError):
        embedding.get_embedder()


def test_local_embedder_lazy_import_error_is_clear(workspace, monkeypatch):
    """If sentence-transformers is not installed, LocalEmbedder must fail
    with a clear redirect message rather than a cryptic ImportError."""
    embedding = workspace["prove_mcp.embedding"]

    # Force the lazy import to fail by clearing the cached module if any.
    import sys

    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    enc = embedding.LocalEmbedder()
    with pytest.raises(RuntimeError, match="sentence-transformers"):
        enc.embed(["anything"])


def test_openai_embedder_requires_api_key(workspace, monkeypatch):
    embedding = workspace["prove_mcp.embedding"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    enc = embedding.OpenAIEmbedder()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        enc.embed(["anything"])


def test_cosine_handles_unit_vectors(workspace):
    embedding = workspace["prove_mcp.embedding"]
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert embedding.cosine(a, a) == pytest.approx(1.0)
    assert embedding.cosine(a, b) == pytest.approx(0.0)


def test_cosine_dim_mismatch_raises(workspace):
    embedding = workspace["prove_mcp.embedding"]
    with pytest.raises(ValueError, match="dim mismatch"):
        embedding.cosine([1.0, 0.0], [0.0, 1.0, 0.0])
