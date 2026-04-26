#!/usr/bin/env python
"""Block direct access to held-out data and unsupported report writes."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterator

from claudescientist.runtime import heldout_root, state_db_path
from verify_mcp.provenance import METRIC_RE

DB = state_db_path()
HELDOUT_PATH_RE = re.compile(
    r"(?i)(?:^|[\\/])\.research-agent[\\/](?:heldout|held_out|held-out)(?:[\\/]|$)"
)
HELDOUT_POINTER_RE = re.compile(
    r"(?i)(?:^|[\\/])[^\\/]*\.(?:heldout|held_out|held-out)-pointer(?:[\\/]|$)"
)
PATH_FRAGMENT_RE = re.compile(
    r"""
    (?:
        [A-Za-z]:[\\/][^\s"'`<>|]+
        |
        ~[\\/][^\s"'`<>|]+
        |
        \.\.?[\\/][^\s"'`<>|]+
        |
        [^\s"'`<>|]+[\\/][^\s"'`<>|]+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
HELDOUT_POINTER_SUFFIXES = (".heldout-pointer", ".held_out-pointer", ".held-out-pointer")
STRIP_CHARS = "`'\"()[]{}.,;"


def _iter_strings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _normalize_text(text: str) -> str:
    normalized = os.path.expandvars(os.path.expanduser(text)).replace("\\", "/")
    return re.sub(r"/+", "/", normalized)


def _clean_candidate(text: str) -> str:
    return text.strip().strip(STRIP_CHARS)


def _candidate_paths(text: str) -> Iterator[str]:
    expanded = os.path.expandvars(os.path.expanduser(text))
    seen: set[str] = set()
    for match in PATH_FRAGMENT_RE.finditer(expanded):
        candidate = _clean_candidate(match.group(0))
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate
    for token in expanded.split():
        candidate = _clean_candidate(token)
        lowered = candidate.lower()
        if candidate and any(suffix in lowered for suffix in HELDOUT_POINTER_SUFFIXES):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate


def _heldout_roots() -> list[Path]:
    roots = [heldout_root()]
    if DB.exists():
        try:
            con = sqlite3.connect(str(DB), timeout=2.0)
            rows = con.execute(
                """
                SELECT heldout_path
                FROM ver_heldout_budgets
                WHERE heldout_path IS NOT NULL
                """
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            try:
                con.close()
            except UnboundLocalError:
                pass
        roots.extend(Path(str(row[0])).expanduser() for row in rows)
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve(strict=False)).replace("\\", "/").lower().rstrip("/")
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


def _is_within(path: Path, root: Path) -> bool:
    candidate = str(path.resolve(strict=False)).replace("\\", "/").lower().rstrip("/")
    root_text = str(root.resolve(strict=False)).replace("\\", "/").lower().rstrip("/")
    return candidate == root_text or candidate.startswith(root_text + "/")


def _looks_like_heldout_reference(text: str) -> bool:
    normalized = _normalize_text(text)
    return bool(HELDOUT_PATH_RE.search(normalized) or HELDOUT_POINTER_RE.search(normalized))


def _should_block_heldout(strings: list[str]) -> bool:
    roots = _heldout_roots()
    for text in strings:
        if _looks_like_heldout_reference(text):
            return True
        for candidate in _candidate_paths(text):
            lowered = candidate.lower()
            if any(lowered.endswith(suffix) for suffix in HELDOUT_POINTER_SUFFIXES):
                return True
            try:
                resolved = Path(os.path.expandvars(os.path.expanduser(candidate)))
            except (OSError, ValueError):
                continue
            if any(_is_within(resolved, root) for root in roots):
                return True
    return False


def _deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def _missing_provenance(values: list[str]) -> list[str]:
    if not DB.exists():
        return values
    con = sqlite3.connect(str(DB), timeout=2.0)
    try:
        missing: list[str] = []
        for value in values:
            row = con.execute(
                "SELECT 1 FROM ver_provenance WHERE value = ? LIMIT 1",
                (value,),
            ).fetchone()
            if row is None:
                missing.append(value)
        return missing
    except sqlite3.OperationalError:
        return values
    finally:
        con.close()


def _should_verify_markdown(path_value: str) -> bool:
    normalized = path_value.replace("\\", "/").lower()
    if not normalized.endswith(".md"):
        return False
    parts = [part for part in normalized.split("/") if part]
    return any(part in {"reports", "writeup"} for part in parts)


def _metric_values_from_text(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for match in METRIC_RE.finditer(text):
        value = match.group("value")
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    if os.environ.get("RESEARCH_AGENT_VERIFY") == "1":
        print("{}")
        return
    tool_input = payload.get("tool_input", {})
    strings = list(_iter_strings(tool_input))
    if _should_block_heldout(strings):
        _deny("held-out dataset access only via query_heldout")
        return

    path_value = ""
    for key in ("file_path", "path"):
        candidate = tool_input.get(key)
        if isinstance(candidate, str):
            path_value = candidate
            break
    if _should_verify_markdown(path_value):
        numeric_values = _metric_values_from_text("\n".join(strings))
        if numeric_values:
            missing = _missing_provenance(numeric_values)
            if missing:
                _deny(
                    "Markdown write blocked. Missing provenance for numeric claims: "
                    + ", ".join(missing[:5])
                )
                return
    print("{}")


if __name__ == "__main__":
    main()
