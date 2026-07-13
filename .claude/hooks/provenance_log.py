#!/usr/bin/env python
"""Extract numeric evidence from Bash output and store it in ver_provenance."""

from __future__ import annotations

import hashlib
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
from verify_mcp.run_manifest import capture_run_manifest, store_run_manifest

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
            cursor = con.execute(
                """
                INSERT INTO ver_provenance(claim, value, session_id, source_command, created_at)
                VALUES(?,?,?,?,?)
                """,
                (claim, value, session_id, command, datetime.now(timezone.utc).isoformat()),
            )
            provenance_id = int(cursor.lastrowid)
            manifest = capture_run_manifest(command=command)
            try:
                store_run_manifest(con, manifest, provenance_id=provenance_id)
                input_hashes = [
                    {"path": entry["path"], "sha256": entry["sha256"]}
                    for entry in manifest["files"]
                ]
                encoded_inputs = json.dumps(input_hashes, ensure_ascii=True)
                con.execute(
                    """
                    INSERT INTO ver_provenance_dag(
                      prov_id, input_hashes, output_hash, parent_prov_ids,
                      stale, refreshed_at
                    ) VALUES(?, ?, ?, '[]', 0, CURRENT_TIMESTAMP)
                    """,
                    (
                        provenance_id,
                        encoded_inputs,
                        hashlib.sha256(encoded_inputs.encode("utf-8")).hexdigest(),
                    ),
                )
            except sqlite3.OperationalError:
                # A pre-v5.1 database may not have manifest tables yet. Keep
                # the numeric evidence and let the next normal bootstrap add
                # the new schema rather than making the lifecycle hook fail.
                pass
        con.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    print("{}")


if __name__ == "__main__":
    main()
