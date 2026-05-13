#!/usr/bin/env python
"""Extract numeric evidence from Bash output and store it in ver_provenance."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any

from claudescientist.runtime import (
    connect_existing_sqlite,
    extract_labeled_metric_records,
    state_db_path,
)

DB = state_db_path()


def _db_available() -> bool:
    con = connect_existing_sqlite(DB)
    if con is None:
        return False
    con.close()
    return True


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


def _extract_labeled_records(text: str) -> list[tuple[str, str]]:
    return extract_labeled_metric_records(text)


def collect_records(payload: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    tool_name = str(payload.get("tool_name", ""))
    if tool_name != "Bash" or not _db_available():
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

    con = connect_existing_sqlite(DB)
    if con is None:
        print("{}")
        return
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
