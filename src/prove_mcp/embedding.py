"""Embedding adapter layer for prove_mcp (P2).

Three backends, selected at runtime via the ``RESEARCH_AGENT_EMBED_BACKEND``
environment variable:

- ``mock`` -- deterministic hash-bag-of-words embedder. No external
  dependencies. Used by the test suite and as a smoke-mode default. Same
  text always maps to the same vector; texts sharing tokens are nearby.
- ``local`` (default) -- ``sentence-transformers`` model loaded lazily.
  English: ``all-MiniLM-L6-v2``; Chinese: ``BAAI/bge-small-zh-v1.5``.
  Override via ``RESEARCH_AGENT_EMBED_MODEL``.
- ``openai`` -- OpenAI ``text-embedding-3-large``. Requires
  ``OPENAI_API_KEY``. Lazy-imported so the dependency is optional.

Critical invariant (ADR 0008 / architecture.md §13): retrieval refuses to
mix vectors produced by different backends or different dimensions. The
caller (``ingest_proof_corpus`` and ``retrieve_skeletons``) is expected to
record the backend ``name`` and ``dim`` it ingested under and reject
queries against a mismatched store.
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

DEFAULT_BACKEND = "local"
MOCK_DIM = 64
LOCAL_DEFAULT_MODEL = "all-MiniLM-L6-v2"
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
    """Common interface for every embedding backend."""

    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one unit-length vector per input text, in order."""
        raise NotImplementedError


class MockEmbedder(EmbeddingBackend):
    """Deterministic hash-bag-of-words embedder.

    Each token contributes 1.0 to a single coordinate determined by
    ``sha256(token) mod dim``. The result is L2-normalized. Same text
    always yields the same vector; texts sharing tokens are near-by under
    cosine similarity.
    """

    name = "mock"

    def __init__(self, dim: int = MOCK_DIM) -> None:
        if dim <= 0:
            raise ValueError("MockEmbedder dim must be positive")
        self.dim = int(dim)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in _tokenize(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "big") % self.dim
                vec[idx] += 1.0
            out.append(_normalize(vec))
        return out


class LocalEmbedder(EmbeddingBackend):
    """Lazy sentence-transformers wrapper.

    The model is loaded on first ``embed`` call so the import overhead is
    paid only when retrieval is actually used. Tests should not exercise
    this backend; they should run under ``mock``.
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
                "package. Install via `uv add sentence-transformers` or "
                "switch backend with RESEARCH_AGENT_EMBED_BACKEND=mock."
            ) from exc
        self._model = SentenceTransformer(self.model_name)
        self._dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            self._load()
        assert self._model is not None
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        return [list(map(float, row)) for row in vectors]


class OpenAIEmbedder(EmbeddingBackend):
    """Lazy OpenAI text-embedding-3-large wrapper.

    Requires ``OPENAI_API_KEY``. Batches at most 100 inputs per call per
    OpenAI's documented limit.
    """

    name = "openai"

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get(ENV_MODEL) or OPENAI_DEFAULT_MODEL
        self._client = None
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        # text-embedding-3-large is 3072-dim by default. The API also
        # accepts a `dimensions` parameter to truncate; we use the full
        # vector and report it after the first call.
        if self._dim is None:
            self._dim = 3072
        return self._dim

    def _load(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OpenAIEmbedder requires OPENAI_API_KEY in the environment."
            )
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "OpenAIEmbedder requires the optional 'openai' package. "
                "Install via `uv add openai` or switch backend with "
                "RESEARCH_AGENT_EMBED_BACKEND=local."
            ) from exc
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
        return out

    def _embed_batch(self, batch: Sequence[str]) -> list[list[float]]:
        assert self._client is not None
        resp = self._client.embeddings.create(model=self.model_name, input=list(batch))
        rows = [list(item.embedding) for item in resp.data]
        # Always normalize to unit length so cosine == dot product.
        return [_normalize(row) for row in rows]


def get_embedder() -> EmbeddingBackend:
    """Return the embedder selected by ``RESEARCH_AGENT_EMBED_BACKEND``.

    Default is ``local`` (sentence-transformers). Tests should set the env
    var to ``mock`` so they do not require any optional dependency or
    network access.
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
    """Cosine similarity for two unit-length vectors. Falls back to
    full normalization if the inputs are not already normalized."""
    if len(a) != len(b):
        raise ValueError(f"vector dim mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    # If both are unit-length, dot is the cosine. Otherwise normalize.
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    if abs(norm_a - 1.0) < 1e-6 and abs(norm_b - 1.0) < 1e-6:
        return dot
    return dot / (norm_a * norm_b)
