"""Helpers for extracting numeric evidence from tool outputs."""

from __future__ import annotations

import re

METRIC_RE = re.compile(
    r"(?P<label>(?:acc(?:uracy)?|f1|auc|loss|precision|recall|mse|rmse|mae|bleu|rouge|score|metric)[^:=\n]{0,24})"
    r"[:= ]+"
    r"(?P<value>[-+]?\d+(?:\.\d+)?%?)",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?%?")


def extract_metric_tokens(text: str) -> list[str]:
    values = [match.group("value") for match in METRIC_RE.finditer(text)]
    if values:
        return values
    return NUMBER_RE.findall(text)


def normalize_claim(claim: str) -> str:
    return " ".join(claim.strip().split()).lower()


def normalize_value(value: str | int | float) -> str:
    text = str(value).strip()
    match = NUMBER_RE.fullmatch(text)
    if match:
        return match.group(0)
    return text
