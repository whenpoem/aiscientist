#!/usr/bin/env python
"""Drain queued cockpit interventions into additionalContext."""

from __future__ import annotations

import json
import sqlite3
import sys

from claudescientist.runtime import state_db_path

DB = state_db_path()


def drain() -> str:
    if not DB.exists():
        return ""
    con = sqlite3.connect(str(DB), timeout=2.0)
    con.row_factory = sqlite3.Row
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
    _ = json.loads(sys.stdin.read() or "{}")
    text = drain()
    if text:
        print(json.dumps({"hookSpecificOutput": {"additionalContext": text}}))
    else:
        print("{}")


if __name__ == "__main__":
    main()
