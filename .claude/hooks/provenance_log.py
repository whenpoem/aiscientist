#!/usr/bin/env python
"""Extract numeric evidence from Bash output and store it in ver_provenance."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any

from claudescientist.runtime import extract_metric_tokens, state_db_path

DB = state_db_path()
METRIC_WORDS = (
    "acc",
    "accuracy",
    "f1",
    "auc",
    "auroc",
    "auprc",
    "loss",
    "precision",
    "recall",
    "mse",
    "rmse",
    "mae",
    "bleu",
    "rouge",
    "score",
    "metric",
    "error",
)
NOISE_WORDS = (
    "epoch",
    "step",
    "seed",
    "batch",
    "sample",
    "param",
    "second",
    "minute",
    "hour",
    "iteration",
    "iter",
    "token",
    "ms",
    "sec",
    "time",
    "throughput",
    "speed",
    "wall",
)
METRIC_LABEL_FRAGMENT = (
    r"(?:best|train|val|valid|validation|dev|test|holdout|oof|cv|cross[ -]?val)?"
    r"[ _-]*"
    r"(?:top[ -]?\d+[ _-]*)?"
    r"(?:acc(?:uracy)?|f1(?:[ _-]?score)?|auc|auroc|auprc|loss|precision|recall|"
    r"mse|rmse|mae|bleu|rouge(?:[- ]?[a-z0-9]+)?|score|metric|error)"
)
LABEL_BEFORE_VALUE_RE = re.compile(
    rf"(?P<label>{METRIC_LABEL_FRAGMENT})\s*(?:[:=]|is)\s*(?P<value>[-+]?\d+(?:\.\d+)?%?)",
    re.IGNORECASE,
)
LABEL_AND_VALUE_RE = re.compile(
    rf"(?P<label>{METRIC_LABEL_FRAGMENT})\s+(?P<value>[-+]?\d+(?:\.\d+)?%?)",
    re.IGNORECASE,
)
VALUE_BEFORE_LABEL_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<value>[-+]?\d+(?:\.\d+)?%?)\s+(?P<label>{METRIC_LABEL_FRAGMENT})\b",
    re.IGNORECASE,
)


def _flatten_output(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _flatten_output(item)))
    if isinstance(value, dict):
        ordered_keys = ("stdout", "stderr", "output", "result", "message", "text", "content")
        parts = [_flatten_output(value[key]) for key in ordered_keys if key in value]
        extra = [
            _flatten_output(item)
            for key, item in value.items()
            if key not in ordered_keys and key not in {"command", "exit_code", "returncode"}
        ]
        return "\n".join(part for part in parts + extra if part)
    return ""


def _normalize_claim(label: str) -> str:
    label = label.strip().lower()
    label = label.replace("%", "pct")
    label = label.replace("/", "_")
    label = re.sub(r"[^a-z0-9]+", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")
    return label[:64]


def _looks_like_metric_label(label: str) -> bool:
    lowered = label.lower()
    has_metric_word = any(word in lowered for word in METRIC_WORDS)
    has_noise_word = any(word in lowered for word in NOISE_WORDS)
    return has_metric_word and not has_noise_word


def _extract_labeled_records(text: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        found_on_line = False
        for pattern in (LABEL_BEFORE_VALUE_RE, LABEL_AND_VALUE_RE, VALUE_BEFORE_LABEL_RE):
            for match in pattern.finditer(line):
                label = _normalize_claim(match.group("label"))
                value = match.group("value")
                if not label or not _looks_like_metric_label(label):
                    continue
                record = (label, value)
                if record in seen:
                    continue
                seen.add(record)
                records.append(record)
                found_on_line = True
        if found_on_line:
            continue
        lowered = line.lower()
        if not any(word in lowered for word in METRIC_WORDS):
            continue
        values = extract_metric_tokens(line)
        if not values:
            continue
        fallback_label = _normalize_claim(line.split(":")[0].split("=")[0]) or "bash_metric"
        if not _looks_like_metric_label(fallback_label):
            fallback_label = "bash_metric"
        for value in values[:1]:
            record = (fallback_label, value)
            if record in seen:
                continue
            seen.add(record)
            records.append(record)
    return records


def collect_records(payload: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    tool_name = str(payload.get("tool_name", ""))
    if tool_name != "Bash" or not DB.exists():
        return []
    tool_input = payload.get("tool_input", {})
    command = str(tool_input.get("command", ""))[:500]
    output = _flatten_output(
        payload.get("tool_output")
        or payload.get("tool_response")
        or payload.get("output")
        or payload.get("stdout")
        or ""
    )
    if not output.strip():
        return []
    session_id = str(payload.get("session_id", "unknown"))
    return [
        (claim, value, session_id, command)
        for claim, value in _extract_labeled_records(output)
    ]


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    records = collect_records(payload)
    if not records:
        print("{}")
        return

    con = sqlite3.connect(str(DB), timeout=2.0)
    try:
        for claim, value, session_id, command in records:
            con.execute(
                """
                INSERT INTO ver_provenance(claim, value, session_id, source_command, created_at)
                VALUES(?,?,?,?,?)
                """,
                (claim, value, session_id, command, datetime.now(timezone.utc).isoformat()),
            )
        con.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    print("{}")


if __name__ == "__main__":
    main()
