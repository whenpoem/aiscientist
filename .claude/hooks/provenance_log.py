#!/usr/bin/env python
"""Extract numeric evidence from Bash output and store it in ver_provenance."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from verify_mcp.provenance import extract_metric_tokens

DB = Path(".research-agent/state.db")


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    tool_name = payload.get("tool_name", "")
    if tool_name != "Bash" or not DB.exists():
        print("{}")
        return

    tool_input = payload.get("tool_input", {})
    output = (
        payload.get("tool_output")
        or payload.get("tool_response")
        or payload.get("output")
        or payload.get("stdout")
        or ""
    )
    if isinstance(output, dict):
        output = json.dumps(output, ensure_ascii=True)
    if not isinstance(output, str) or not output.strip():
        print("{}")
        return

    values = extract_metric_tokens(output)
    if not values:
        print("{}")
        return

    session_id = str(payload.get("session_id", "unknown"))
    command = str(tool_input.get("command", ""))[:500]
    con = sqlite3.connect(str(DB), timeout=2.0)
    try:
        for value in values:
            con.execute(
                """
                INSERT INTO ver_provenance(claim, value, session_id, source_command, created_at)
                VALUES(?,?,?,?,?)
                """,
                ("bash_number", value, session_id, command, datetime.now(timezone.utc).isoformat()),
            )
        con.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    print("{}")


if __name__ == "__main__":
    main()

