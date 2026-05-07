"""Shared helpers used across more than one prove_mcp.tools submodule."""

from __future__ import annotations

import sqlite3
import struct
from typing import Sequence

from claudescientist.runtime import emit_cockpit_event


def _emit_event(con: sqlite3.Connection, kind: str, payload: dict) -> None:
    """Emit a cockpit event, swallowing transient SQLite errors.

    Mirrors ``memory_mcp.tools._common._emit_event`` so cross-trunk event
    semantics stay aligned.
    """
    try:
        emit_cockpit_event(con, kind, payload)
    except sqlite3.Error:
        return


def encode_vector(vec: Sequence[float]) -> bytes:
    """Serialise a float32 vector as a packed little-endian blob."""
    if not isinstance(vec, (list, tuple)):
        vec = list(vec)
    return struct.pack(f"<{len(vec)}f", *(float(v) for v in vec))


def decode_vector(blob: bytes, dim: int) -> list[float]:
    """Inverse of :func:`encode_vector`. ``dim`` must match the producer."""
    if dim <= 0:
        raise ValueError("dim must be positive")
    expected = dim * 4
    if len(blob) != expected:
        raise ValueError(
            f"vector blob length mismatch: expected {expected} bytes for dim {dim}, "
            f"got {len(blob)}"
        )
    return list(struct.unpack(f"<{dim}f", blob))


def _normalize_keywords(keywords: Sequence[str]) -> list[str]:
    """Strip + lowercase + dedupe while preserving first-seen order."""
    seen: dict[str, None] = {}
    for kw in keywords or []:
        token = (kw or "").strip().lower()
        if not token:
            continue
        seen.setdefault(token, None)
    return list(seen.keys())
