#!/usr/bin/env python
"""Drain queued cockpit interventions into additionalContext."""

from __future__ import annotations

import json
import sqlite3
import sys

from claudescientist.runtime import connect_existing_sqlite, state_db_path

DB = state_db_path()


def drain() -> str:
    con = connect_existing_sqlite(DB)
    if con is None:
        return ""
    try:
        rows = con.execute(
            """
            SELECT id, kind, target, payload
            FROM cockpit_interventions
            WHERE delivered_at IS NULL
            ORDER BY created_at, id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        con.close()
        return ""
    if not rows:
        con.close()
        return ""
    ids = [row["id"] for row in rows]
    blocks = [
        f"- [{row['kind']}] target={row['target'] or 'global'}: {row['payload'] or ''}".strip()
        for row in rows
    ]
    placeholders = ",".join("?" for _ in ids)
    con.execute(
        (
            "UPDATE cockpit_interventions "
            f"SET delivered_at = datetime('now') WHERE id IN ({placeholders})"
        ),
        ids,
    )
    con.commit()
    con.close()
    return "Cockpit interventions to respect before continuing:\n\n" + "\n".join(blocks)


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    event_name = str(payload.get("hook_event_name") or "")
    if event_name not in {"UserPromptSubmit", "Stop"}:
        print("{}")
        return
    text = drain()
    if text:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": event_name,
                        "additionalContext": text,
                    }
                }
            )
        )
        return
    print("{}")


if __name__ == "__main__":
    main()
