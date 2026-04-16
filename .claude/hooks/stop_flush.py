#!/usr/bin/env python
"""Append a turn-end event for cockpit consumers."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(".research-agent/state.db")


def main() -> None:
    _ = json.loads(sys.stdin.read() or "{}")
    if DB.exists():
        con = sqlite3.connect(str(DB), timeout=2.0)
        try:
            con.execute(
                "INSERT INTO cockpit_events(kind, payload, created_at) VALUES(?,?,?)",
                ("turn_end", "{}", datetime.now(timezone.utc).isoformat()),
            )
            con.commit()
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    print("{}")


if __name__ == "__main__":
    main()

