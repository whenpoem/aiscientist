"""Embedding adapter tests (P2 + v4.2.0a0)."""

from __future__ import annotations

import pytest


def test_mock_embedder_is_deterministic(workspace):
    embedding = workspace["prove_mcp.embedding"]
    a = embedding.MockEmbedder().embed(["sample mean unbiased"])
    b = embedding.MockEmbedder().embed(["sample mean unbiased"])
    assert a == b


def test_mock_embedder_exposes_model_name(workspace):
    """Every backend must expose a stable model identifier so the corpus
    can distinguish multiple models living under the same backend
    (ADR 0010)."""
    embedding = workspace["prove_mcp.embedding"]
    enc = embedding.MockEmbedder()
    assert enc.model_name == f"mock-dim{enc.dim}"


def test_local_default_model_is_qwen3(workspace):
    """v4.2.0a0 default for the `local` backend.

    Tests do not actually load Qwen3 — the mock fixture is in effect —
    but the module-level default must reflect the change so users who
    leave RESEARCH_AGENT_EMBED_MODEL unset get the multilingual model."""
    embedding = workspace["prove_mcp.embedding"]
    assert embedding.LOCAL_DEFAULT_MODEL == "Qwen/Qwen3-Embedding-0.6B"


def test_openai_backend_reads_base_url_from_env(workspace, monkeypatch):
    embedding = workspace["prove_mcp.embedding"]
    monkeypatch.setenv(embedding.ENV_OPENAI_BASE_URL, "https://example.test/v1")
    enc = embedding.OpenAIEmbedder()
    assert enc.base_url == "https://example.test/v1"


def test_openai_backend_constructor_overrides_env(workspace, monkeypatch):
    embedding = workspace["prove_mcp.embedding"]
    monkeypatch.setenv(embedding.ENV_OPENAI_BASE_URL, "https://from-env.test/v1")
    enc = embedding.OpenAIEmbedder(base_url="https://from-arg.test/v1")
    assert enc.base_url == "https://from-arg.test/v1"


def test_openai_backend_clears_base_url_when_unset(workspace, monkeypatch):
    embedding = workspace["prove_mcp.embedding"]
    monkeypatch.delenv(embedding.ENV_OPENAI_BASE_URL, raising=False)
    enc = embedding.OpenAIEmbedder()
    assert enc.base_url is None


def test_openai_backend_dim_probed_on_first_embed(workspace, monkeypatch):
    """The dim must come from the first response, not a hardcoded constant.

    This guards against the v4.1 regression where every OpenAI-compatible
    provider was assumed to be 3072-dim (true for OpenAI's
    text-embedding-3-large, wrong for DashScope's 1024-dim model, etc.)."""
    embedding = workspace["prove_mcp.embedding"]

    enc = embedding.OpenAIEmbedder()
    enc._client = _FakeOpenAIClient(dim=1024)
    out = enc.embed(["one"])
    assert len(out) == 1
    assert len(out[0]) == 1024
    assert enc._dim == 1024
    # Subsequent .dim reads must not trigger a re-probe.
    assert enc.dim == 1024


def test_openai_backend_dim_property_triggers_probe(workspace, monkeypatch):
    embedding = workspace["prove_mcp.embedding"]
    enc = embedding.OpenAIEmbedder()
    enc._client = _FakeOpenAIClient(dim=768)
    assert enc.dim == 768


class _FakeOpenAIClient:
    """Stand-in for openai.OpenAI used to test dim-probing without hitting
    the network or requiring the openai package to be installed."""

    def __init__(self, dim: int) -> None:
        self._dim = dim
        self.embeddings = self  # let resp.data style work via the same obj

    def create(self, *, model, input):
        # Mimic the OpenAI response shape: object with `.data`, each item
        # carrying `.embedding`. Use a per-token-dependent vector so the
        # downstream normaliser does something non-trivial.
        del model  # unused in the fake
        rows = []
        for text in input:
            base = (sum(ord(c) for c in text) % 7) + 1
            vec = [base * 0.1] * self._dim
            rows.append(_Item(vec))
        return _Resp(rows)


class _Resp:
    def __init__(self, data):
        self.data = data


class _Item:
    def __init__(self, vec):
        self.embedding = vec


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
