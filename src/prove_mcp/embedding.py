"""Embedding adapter layer for prove_mcp.

Three backends, selected at runtime via the ``RESEARCH_AGENT_EMBED_BACKEND``
environment variable:

- ``mock`` — deterministic hash-bag-of-words embedder. No external
  dependencies. Used by the test suite and as a smoke-mode default. The
  same text always maps to the same vector; texts sharing tokens are
  nearby under cosine similarity.
- ``local`` (default) — ``sentence-transformers`` model loaded lazily.
  The default model is ``Qwen/Qwen3-Embedding-0.6B`` (multilingual,
  ~600 MB download on first use). Override via the
  ``RESEARCH_AGENT_EMBED_MODEL`` env var; legacy users can pin
  ``all-MiniLM-L6-v2`` (384-dim, English-only, ~80 MB).
- ``openai`` — any OpenAI-compatible embeddings endpoint. By default
  this targets ``api.openai.com`` and the ``text-embedding-3-large``
  model. Set ``RESEARCH_AGENT_EMBED_BASE_URL`` to redirect to a
  compatible provider (DashScope, Jina, Voyage, GLM, …) and
  ``RESEARCH_AGENT_EMBED_MODEL`` to switch the model. The vector
  dimension is discovered on the first call rather than hardcoded.

Critical invariant (ADR 0008 + ADR 0010 / architecture.md §13):
retrieval refuses to mix vectors produced by different backends, models,
or dimensions. The caller (``ingest_proof_corpus`` and
``retrieve_skeletons``) records the backend ``name``, the model
identifier, and the vector ``dim`` it ingested under and rejects queries
against a mismatched store. To switch any of those three, the caller
must re-ingest (see ``scripts/reindex_proof_corpus.py``).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod
from typing import Sequence

ENV_BACKEND = "RESEARCH_AGENT_EMBED_BACKEND"
ENV_MODEL = "RESEARCH_AGENT_EMBED_MODEL"
ENV_OPENAI_BASE_URL = "RESEARCH_AGENT_EMBED_BASE_URL"

DEFAULT_BACKEND = "local"
MOCK_DIM = 64
# Qwen3-Embedding-0.6B is multilingual and ~600 MB; it covers both
# English and Chinese clusters in the seed proof corpus. Users who want
# the smaller English-only model can set
# RESEARCH_AGENT_EMBED_MODEL=all-MiniLM-L6-v2 to revert.
LOCAL_DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"
OPENAI_DEFAULT_MODEL = "text-embedding-3-large"

_TOKEN_RE = re.compile(r"[A-Za-z0-9_一-鿿]{2,}")


def _tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(text or "")]


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


class EmbeddingBackend(ABC):
    """Common interface for every embedding backend.

    Subclasses must set ``name`` (a stable short string used as the
    ``embed_backend`` value in ``prv_corpus_keywords``) and expose a
    ``model_name`` attribute identifying the specific model in use (used
    as the ``embedding_model`` column). The ``dim`` property must return
    a positive integer; it may load lazily on first access.
    """

    name: str
    model_name: str

    @property
    @abstractmethod
    def dim(self) -> int:
        """Vector dimension. Subclasses may discover this lazily."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one unit-length vector per input text, in order."""
        raise NotImplementedError


class MockEmbedder(EmbeddingBackend):
    """Deterministic hash-bag-of-words embedder.

    Each token contributes 1.0 to a single coordinate determined by
    ``sha256(token) mod dim``. The result is L2-normalized. The same
    text always yields the same vector; texts sharing tokens come out
    near each other under cosine similarity.
    """

    name = "mock"

    def __init__(self, dim: int = MOCK_DIM) -> None:
        if dim <= 0:
            raise ValueError("MockEmbedder dim must be positive")
        self._dim = int(dim)
        # Mock is parameterized only by dim; we tag the model identifier
        # with the dim so two MockEmbedder instances with different dims
        # produce distinguishable corpus metadata.
        self.model_name = f"mock-dim{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            for token in _tokenize(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "big") % self._dim
                vec[idx] += 1.0
            out.append(_normalize(vec))
        return out


class LocalEmbedder(EmbeddingBackend):
    """Lazy sentence-transformers wrapper.

    The model loads on first ``embed`` call so the heavy import is paid
    only once retrieval actually runs. Tests should never exercise this
    backend; they should run under ``mock``.
    """

    name = "local"

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get(ENV_MODEL) or LOCAL_DEFAULT_MODEL
        self._model = None
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._load()
        assert self._dim is not None
        return self._dim

    def _load(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "LocalEmbedder requires the optional 'sentence-transformers' "
                "package. Install via `uv sync --extra proof` (recommended) or "
                "`uv add sentence-transformers`, or switch backend with "
                "RESEARCH_AGENT_EMBED_BACKEND=mock."
            ) from exc
        self._model = SentenceTransformer(self.model_name)
        # sentence-transformers 5.x renamed get_sentence_embedding_dimension
        # to get_embedding_dimension. Prefer the new name and fall back
        # for older releases.
        get_dim = getattr(
            self._model, "get_embedding_dimension", None
        ) or self._model.get_sentence_embedding_dimension
        self._dim = int(get_dim())

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            self._load()
        assert self._model is not None
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        return [list(map(float, row)) for row in vectors]


class OpenAIEmbedder(EmbeddingBackend):
    """OpenAI-compatible embeddings client.

    Talks to any provider that exposes the OpenAI embeddings API shape
    (``/v1/embeddings`` with ``model`` + ``input`` parameters returning
    ``{"data": [{"embedding": [...]}], ...}``). The wire protocol is
    pinned by the official ``openai`` Python SDK; providers diverging
    from it (different auth scheme, non-standard error envelopes) are
    out of scope.

    Configuration sources, in precedence order:

    1. Constructor arguments (``model_name``, ``base_url``)
    2. Environment variables (``RESEARCH_AGENT_EMBED_MODEL``,
       ``RESEARCH_AGENT_EMBED_BASE_URL``)
    3. Built-in defaults (``text-embedding-3-large``, OpenAI's public
       endpoint)

    ``OPENAI_API_KEY`` is required regardless of which provider is in
    use; OpenAI-compatible providers accept their own keys through that
    same variable (this is the SDK's contract). Batches at most 100
    inputs per request, matching OpenAI's documented limit; most
    compatible providers tolerate the same ceiling or smaller batches.

    The vector dimension is discovered on the first ``embed`` call
    rather than hardcoded — DashScope's ``text-embedding-v3`` returns
    1024, Jina's ``jina-embeddings-v3`` returns 1024, OpenAI's
    ``text-embedding-3-large`` returns 3072, and so on. Reading
    ``dim`` before the first ``embed`` call triggers a one-input probe.
    """

    name = "openai"

    def __init__(
        self,
        model_name: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model_name = (
            model_name or os.environ.get(ENV_MODEL) or OPENAI_DEFAULT_MODEL
        )
        # base_url=None lets the SDK fall back to its built-in default
        # (api.openai.com). We avoid hardcoding the OpenAI URL so a future
        # SDK change to that default carries through automatically.
        self.base_url = base_url or os.environ.get(ENV_OPENAI_BASE_URL) or None
        self._client = None
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            # Sending one short string is the cheapest legal probe across
            # every compatible provider. The returned vector length is
            # cached for the rest of the process lifetime.
            self.embed(["probe"])
        assert self._dim is not None
        return self._dim

    def _load(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OpenAIEmbedder requires OPENAI_API_KEY in the environment. "
                "OpenAI-compatible providers (DashScope, Jina, Voyage, …) "
                "accept their own API keys through that same variable."
            )
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "OpenAIEmbedder requires the optional 'openai' package. "
                "Install via `uv sync --extra embed-openai` or "
                "`uv sync --extra all`, or switch backend with "
                "RESEARCH_AGENT_EMBED_BACKEND=local."
            ) from exc
        # Passing base_url=None keeps the SDK default; passing a string
        # routes every call to that endpoint.
        if self.base_url:
            self._client = OpenAI(base_url=self.base_url)
        else:
            self._client = OpenAI()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._client is None:
            self._load()
        assert self._client is not None
        out: list[list[float]] = []
        batch: list[str] = []
        for text in texts:
            batch.append(text)
            if len(batch) == 100:
                out.extend(self._embed_batch(batch))
                batch = []
        if batch:
            out.extend(self._embed_batch(batch))
        # Cache the discovered dimension on the first successful response
        # so later .dim reads don't re-probe.
        if out and self._dim is None:
            self._dim = len(out[0])
        return out

    def _embed_batch(self, batch: Sequence[str]) -> list[list[float]]:
        assert self._client is not None
        resp = self._client.embeddings.create(
            model=self.model_name, input=list(batch)
        )
        rows = [list(item.embedding) for item in resp.data]
        # Always normalize to unit length so cosine equals dot product
        # downstream. OpenAI returns unit-length vectors; compatible
        # providers usually do too, but we don't trust that universally.
        return [_normalize(row) for row in rows]


def get_embedder() -> EmbeddingBackend:
    """Return the embedder selected by ``RESEARCH_AGENT_EMBED_BACKEND``.

    The default is ``local`` (sentence-transformers). Tests should set
    the env var to ``mock`` so they need neither the optional
    dependency nor network access.
    """
    raw = (os.environ.get(ENV_BACKEND) or DEFAULT_BACKEND).lower()
    if raw == "mock":
        return MockEmbedder()
    if raw == "local":
        return LocalEmbedder()
    if raw == "openai":
        return OpenAIEmbedder()
    raise ValueError(
        f"Unknown embedding backend {raw!r}; expected one of mock|local|openai"
    )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity for two unit-length vectors.

    Falls back to full normalization when either input isn't already
    unit-length. Raises ``ValueError`` when the dimensions don't match
    so cross-backend mistakes surface immediately instead of returning
    garbage.
    """
    if len(a) != len(b):
        raise ValueError(f"vector dim mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    if abs(norm_a - 1.0) < 1e-6 and abs(norm_b - 1.0) < 1e-6:
        return dot
    return dot / (norm_a * norm_b)
