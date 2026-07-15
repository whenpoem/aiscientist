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

from claudescientist.runtime import (
    connect_existing_sqlite,
    extract_labeled_metric_records,
    heldout_root,
    state_db_path,
)

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
PUBLICATION_ROOTS_ENV = "RESEARCH_AGENT_PUBLICATION_ROOTS"
DEFAULT_PUBLICATION_ROOTS = (
    "reports",
    "writeup",
    "paper",
    "submission",
    "manuscript",
)


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
    con = connect_existing_sqlite(DB)
    if con is not None:
        try:
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


def _claim_variants(claim: str) -> tuple[str, ...]:
    spaced = claim.replace("_", " ")
    underscored = claim.replace(" ", "_")
    return tuple(dict.fromkeys([claim, spaced, underscored]))


def _value_variants(value: str) -> tuple[str, ...]:
    stripped = value.strip()
    bare_percent = stripped[:-1] if stripped.endswith("%") else stripped
    return tuple(dict.fromkeys([stripped, bare_percent]))


def _missing_provenance(records: list[tuple[str, str]]) -> list[str]:
    con = connect_existing_sqlite(DB)
    if con is None:
        return [f"{claim}={value}" for claim, value in records]
    try:
        missing: list[str] = []
        for claim, value in records:
            claim_options = _claim_variants(claim)
            value_options = _value_variants(value)
            claim_marks = ",".join("?" for _ in claim_options)
            value_marks = ",".join("?" for _ in value_options)
            row = con.execute(
                f"""
                SELECT 1
                FROM ver_provenance
                WHERE claim IN ({claim_marks}) AND value IN ({value_marks})
                LIMIT 1
                """,
                (*claim_options, *value_options),
            ).fetchone()
            if row is None:
                row = con.execute(
                    f"""
                    SELECT 1
                    FROM ver_provenance
                    WHERE value IN ({value_marks})
                    LIMIT 1
                    """,
                    value_options,
                ).fetchone()
            if row is None:
                missing.append(f"{claim}={value}")
        return missing
    except sqlite3.OperationalError:
        return [f"{claim}={value}" for claim, value in records]
    finally:
        con.close()


def _should_verify_markdown(path_value: str) -> bool:
    normalized = path_value.replace("\\", "/").lower()
    if not normalized.endswith(".md"):
        return False
    parts = [part for part in normalized.split("/") if part]
    configured = os.environ.get(PUBLICATION_ROOTS_ENV, "").strip()
    roots = (
        tuple(
            root.strip().replace("\\", "/").lower().strip("/")
            for root in re.split(r"[;,]", configured)
            if root.strip()
        )
        if configured
        else DEFAULT_PUBLICATION_ROOTS
    )
    for root in roots:
        if "/" not in root and ":" not in root:
            if root in parts:
                return True
            continue
        candidate = str(Path(path_value).expanduser().resolve(strict=False))
        root_path = str(Path(root).expanduser().resolve(strict=False))
        if candidate.lower().replace("\\", "/").startswith(
            root_path.lower().replace("\\", "/").rstrip("/") + "/"
        ):
            return True
    return False


def _metric_records_from_text(text: str) -> list[tuple[str, str]]:
    return extract_labeled_metric_records(text)


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
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
        metric_records = _metric_records_from_text("\n".join(strings))
        if metric_records:
            missing = _missing_provenance(metric_records)
            if missing:
                _deny(
                    "Markdown write blocked. Missing provenance for numeric claims: "
                    + ", ".join(missing[:5])
                )
                return
    print("{}")


if __name__ == "__main__":
    main()
