"""CascadeTrace: state-change events around a node.

Collects every relevant cockpit event whose payload references the
target node, in chronological order. Renderers display them as a
linear log; the HTML renderer renders nested ``<details>`` so the
user can collapse less-interesting branches.

This DTO does NOT compute closure or implement cross-trunk
propagation. It is purely a history view — the user reads it to
understand what already happened around a node, the cockpit decides
how to display that history.
"""

from __future__ import annotations

import json
import sqlite3

from claudescientist.runtime import connect_sqlite, now_utc_iso, state_db_path
from cockpit.export.dto.base import Report, ReportSection

# Event kinds we treat as "state changes worth tracing". Adding a new
# kind here is the way to extend the trace's coverage; keep this set
# in lockstep with the kinds documented in architecture.md §8.
_TRACED_KINDS: tuple[str, ...] = (
    "graph_delta",
    "failure_added",
    "bt_rating_updated",
    "branch_pause_suggested",
    "branch_paused",
    "branch_promoted",
    "prereg_locked",
    "prereg_resolved",
    "prov_dag_stale",
    "seed_run_recorded",
    "report_generated",
    "intervention",
)


def _connect() -> sqlite3.Connection:
    return connect_sqlite(state_db_path())


def _short(node_id: str) -> str:
    if "_" not in node_id:
        return node_id[:10]
    prefix, suffix = node_id.split("_", 1)
    return f"{prefix}_{suffix[:6]}"


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    return con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone() is not None


def _event_mentions_node(payload: object, node_id: str) -> bool:
    """Walk a parsed JSON payload looking for the node id.

    The cockpit event schema doesn't require a fixed field name —
    different producers use ``node_id``, ``hypothesis_id``,
    ``proposition_id``, etc. We accept any string-typed leaf whose
    value matches.
    """
    if isinstance(payload, dict):
        for value in payload.values():
            if _event_mentions_node(value, node_id):
                return True
    elif isinstance(payload, list):
        for value in payload:
            if _event_mentions_node(value, node_id):
                return True
    elif isinstance(payload, str):
        return payload == node_id
    return False


def _fetch_traced_events(
    con: sqlite3.Connection, node_id: str, limit: int = 200
) -> list[dict]:
    if not _table_exists(con, "cockpit_events"):
        return []
    placeholders = ",".join("?" for _ in _TRACED_KINDS)
    rows = con.execute(
        f"""
        SELECT id, kind, payload, created_at
        FROM cockpit_events
        WHERE kind IN ({placeholders})
        ORDER BY id DESC
        LIMIT ?
        """,
        (*_TRACED_KINDS, limit),
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        raw = row["payload"]
        try:
            payload = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            payload = {}
        if _event_mentions_node(payload, node_id):
            out.append(
                {
                    "id": int(row["id"]),
                    "kind": row["kind"],
                    "created_at": row["created_at"],
                    "payload": payload,
                }
            )
    out.reverse()  # chronological order
    return out


def build_cascade(node_id: str) -> Report:
    """Assemble a CascadeTrace for the given node."""
    con = _connect()
    try:
        node_row = con.execute(
            "SELECT node_id, kind, text FROM mem_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if node_row is None:
            raise ValueError(f"unknown node: {node_id!r}")
        node = dict(node_row)

        sections: list[ReportSection] = [
            ReportSection(
                key="root",
                title="Root node",
                body=(
                    f"id: {node['node_id']}\nkind: {node['kind']}\n\n"
                    f"text:\n{node['text']}"
                ),
            )
        ]

        events = _fetch_traced_events(con, node_id)
        if not events:
            sections.append(
                ReportSection(
                    key="events",
                    title="Events",
                    body=(
                        "No state-change events mentioning this node have "
                        "been recorded."
                    ),
                )
            )
        else:
            lines: list[str] = []
            for event in events:
                payload_text = json.dumps(
                    event["payload"], indent=2, sort_keys=True, ensure_ascii=False
                )
                lines.append(
                    f"  [{event['created_at']}] {event['kind']} (#{event['id']})\n"
                    f"    payload: {payload_text}"
                )
            sections.append(
                ReportSection(
                    key="events",
                    title=f"State-change events ({len(events)})",
                    body="\n\n".join(lines),
                    meta={"count": len(events)},
                )
            )
    finally:
        con.close()

    title = f"Cascade: {_short(node_id)}"
    return Report(
        kind="cascade",
        node_id=node_id,
        title=title,
        generated_at=now_utc_iso(),
        sections=tuple(sections),
    )
