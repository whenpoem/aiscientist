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

DB = Path(".research-agent/state.db")
HELDOUT_RE = re.compile(
    r"(?i)(?:\.research-agent[\\/]+held_out|%USERPROFILE%[\\/]+\.research-agent|~[\\/]+\.research-agent[\\/]+held_out)"
)
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?%?")


def _iter_strings(value) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _deny(reason: str) -> None:
    print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
    raise SystemExit(2)


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


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    if os.environ.get("RESEARCH_AGENT_VERIFY") == "1":
        print("{}")
        return
    tool_input = payload.get("tool_input", {})
    strings = list(_iter_strings(tool_input))
    if any(HELDOUT_RE.search(text.replace("\\", "/")) for text in strings):
        _deny("Held-out data access is restricted to verify-mcp.")

    path_value = ""
    for key in ("file_path", "path"):
        candidate = tool_input.get(key)
        if isinstance(candidate, str):
            path_value = candidate
            break
    if path_value.lower().endswith(".md"):
        numeric_values = NUMBER_RE.findall("\n".join(strings))
        if numeric_values:
            missing = _missing_provenance(numeric_values)
            if missing:
                _deny(f"Markdown write blocked. Missing provenance for numeric claims: {', '.join(missing[:5])}")
    print("{}")


if __name__ == "__main__":
    main()

