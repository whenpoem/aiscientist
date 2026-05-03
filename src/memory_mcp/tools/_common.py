"""Shared helpers and constants used across more than one tools/ submodule.

A helper or constant lives here only when at least two tools/ submodules
need it. Domain-specific helpers stay next to the tools that own them.
"""

from __future__ import annotations

import re
import sqlite3
from uuid import uuid4

from claudescientist.runtime import emit_cockpit_event

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def _node_id(kind: str) -> str:
    """Return a fresh node id with a kind-aware prefix."""
    prefix = {
        "hypothesis": "hyp",
        "evidence": "ev",
        "question": "q",
        "experiment": "exp",
        "conclusion": "con",
    }.get(kind, "node")
    return f"{prefix}_{uuid4().hex[:12]}"


def _fts_query(text: str) -> str:
    """Build an FTS5 prefix-OR query from up to twelve content tokens."""
    tokens = [token.lower() for token in _TOKEN_RE.findall(text)]
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens[:12])


def _emit_event(con, kind: str, payload: dict) -> None:
    """Emit a cockpit event, swallowing transient SQLite errors."""
    try:
        emit_cockpit_event(con, kind, payload)
    except sqlite3.Error:
        return


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def _get_node(con: sqlite3.Connection, node_id: str) -> sqlite3.Row | None:
    return con.execute(
        """
        SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
        FROM mem_nodes
        WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
