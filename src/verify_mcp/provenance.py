"""Helpers for extracting numeric evidence from tool outputs.

Numeric-recognition constants (``METRIC_RE``, ``NUMBER_RE``,
``extract_metric_tokens``) live in :mod:`claudescientist.runtime` because
multiple layers need them: this module, the leakage guard hook, and the
provenance log hook. They are re-exported here for backward compatibility
with code that still imports them from ``verify_mcp.provenance``.
"""

from __future__ import annotations

from claudescientist.runtime import (
    METRIC_RE,
    NUMBER_RE,
    extract_metric_tokens,
)

__all__ = [
    "METRIC_RE",
    "NUMBER_RE",
    "extract_metric_tokens",
    "normalize_claim",
    "normalize_value",
]


def normalize_claim(claim: str) -> str:
    return " ".join(claim.strip().split()).lower()


def normalize_value(value: str | int | float) -> str:
    text = str(value).strip()
    match = NUMBER_RE.fullmatch(text)
    if match:
        return match.group(0)
    return text
