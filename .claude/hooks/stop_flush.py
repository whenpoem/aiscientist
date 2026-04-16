#!/usr/bin/env python
"""Append a turn-end event with a useful database delta for cockpit consumers."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any

from claudescientist.runtime import runtime_path, state_db_path

DB = state_db_path()
STATE = runtime_path("stop_flush_state.json")
SAMPLE_LIMIT = 6


def _safe_rows(
    con: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    try:
        rows = con.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(row) for row in rows]


def _read_state() -> dict[str, Any]:
    if not STATE.exists():
        return {}
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def _shorten(text: str, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _sample(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return items[:SAMPLE_LIMIT]


def _snapshot(con: sqlite3.Connection) -> dict[str, Any]:
    nodes = _safe_rows(
        con,
        """
        SELECT rowid, node_id, kind, text, state
        FROM mem_nodes
        ORDER BY rowid
        """,
    )
    edges = _safe_rows(
        con,
        """
        SELECT edge_id, src, dst, relation, coalesce(rationale, '') AS rationale
        FROM mem_edges
        ORDER BY edge_id
        """,
    )
    failures = _safe_rows(
        con,
        """
        SELECT failure_id, trigger, symptom, coalesce(root_cause, '') AS root_cause, seen_count
        FROM mem_failures
        ORDER BY failure_id
        """,
    )
    papers = _safe_rows(
        con,
        """
        SELECT paper_id, source, coalesce(title, '') AS title
        FROM mem_lit_compressed
        ORDER BY rowid
        """,
    )
    provenance = _safe_rows(
        con,
        """
        SELECT id, claim, value, coalesce(source_command, '') AS source_command
        FROM ver_provenance
        ORDER BY id
        """,
    )

    node_states = {row["node_id"]: row["state"] for row in nodes}
    node_details = {
        row["node_id"]: {
            "kind": row["kind"],
            "text": row["text"],
            "state": row["state"],
        }
        for row in nodes
    }
    summary = {
        "nodes_total": len(nodes),
        "active_nodes": sum(1 for row in nodes if row["state"] == "active"),
        "refuted_nodes": sum(1 for row in nodes if row["state"] == "refuted"),
        "edges_total": len(edges),
        "failures_total": len(failures),
        "failure_hits_total": sum(int(row["seen_count"]) for row in failures),
        "papers_total": len(papers),
        "provenance_total": len(provenance),
    }
    return {
        "summary": summary,
        "state": {
            "node_states": node_states,
            "node_details": node_details,
            "edge_ids": [int(row["edge_id"]) for row in edges],
            "failure_seen_counts": {
                str(row["failure_id"]): int(row["seen_count"]) for row in failures
            },
            "paper_ids": [str(row["paper_id"]) for row in papers],
            "provenance_max_id": max((int(row["id"]) for row in provenance), default=0),
        },
        "rows": {
            "nodes": nodes,
            "edges": edges,
            "failures": failures,
            "papers": papers,
            "provenance": provenance,
        },
    }


def _build_delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev_node_states = previous.get("node_states", {})
    prev_edge_ids = {int(edge_id) for edge_id in previous.get("edge_ids", [])}
    prev_failure_counts = {
        str(key): int(value) for key, value in previous.get("failure_seen_counts", {}).items()
    }
    prev_paper_ids = {str(paper_id) for paper_id in previous.get("paper_ids", [])}
    prev_provenance_max_id = int(previous.get("provenance_max_id", 0))

    node_details = current["state"]["node_details"]
    new_nodes = [
        {
            "node_id": node["node_id"],
            "kind": node["kind"],
            "state": node["state"],
            "text": _shorten(node["text"]),
        }
        for node in current["rows"]["nodes"]
        if node["node_id"] not in prev_node_states
    ]
    state_changes = [
        {
            "node_id": node_id,
            "kind": node_details[node_id]["kind"],
            "from": prev_node_states[node_id],
            "to": state,
            "text": _shorten(str(node_details[node_id]["text"])),
        }
        for node_id, state in current["state"]["node_states"].items()
        if node_id in prev_node_states and prev_node_states[node_id] != state
    ]
    new_edges = [
        {
            "edge_id": int(edge["edge_id"]),
            "src": edge["src"],
            "dst": edge["dst"],
            "relation": edge["relation"],
        }
        for edge in current["rows"]["edges"]
        if int(edge["edge_id"]) not in prev_edge_ids
    ]
    new_failures = []
    repeated_failures = []
    for failure in current["rows"]["failures"]:
        failure_id = str(failure["failure_id"])
        seen_count = int(failure["seen_count"])
        record = {
            "failure_id": int(failure["failure_id"]),
            "trigger": _shorten(str(failure["trigger"]), 80),
            "symptom": _shorten(str(failure["symptom"]), 100),
            "seen_count": seen_count,
        }
        if failure_id not in prev_failure_counts:
            new_failures.append(record)
            continue
        delta = seen_count - prev_failure_counts[failure_id]
        if delta > 0:
            repeated_failures.append({**record, "new_hits": delta})
    new_papers = [
        {
            "paper_id": paper["paper_id"],
            "source": paper["source"],
            "title": _shorten(str(paper["title"]), 120),
        }
        for paper in current["rows"]["papers"]
        if str(paper["paper_id"]) not in prev_paper_ids
    ]
    new_provenance = [
        {
            "id": int(row["id"]),
            "claim": row["claim"],
            "value": row["value"],
            "source_command": _shorten(str(row["source_command"]), 120),
        }
        for row in current["rows"]["provenance"]
        if int(row["id"]) > prev_provenance_max_id
    ]

    counts = {
        "new_nodes": len(new_nodes),
        "state_changes": len(state_changes),
        "new_edges": len(new_edges),
        "new_failures": len(new_failures),
        "repeated_failures": len(repeated_failures),
        "new_papers": len(new_papers),
        "new_provenance": len(new_provenance),
    }
    return {
        "counts": counts,
        "new_nodes": _sample(new_nodes),
        "state_changes": _sample(state_changes),
        "new_edges": _sample(new_edges),
        "new_failures": _sample(new_failures),
        "repeated_failures": _sample(repeated_failures),
        "new_papers": _sample(new_papers),
        "new_provenance": _sample(new_provenance),
        "has_changes": any(count > 0 for count in counts.values()),
    }


def collect_event_payload(hook_payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not DB.exists():
        return None
    con = sqlite3.connect(str(DB), timeout=2.0)
    con.row_factory = sqlite3.Row
    try:
        previous = _read_state()
        current = _snapshot(con)
        event_payload = {
            "session_id": str((hook_payload or {}).get("session_id", "unknown")),
            "trigger": str((hook_payload or {}).get("hook_event_name", "stop")),
            "summary": current["summary"],
            "delta": _build_delta(previous, current),
        }
        _write_state(current["state"])
        return event_payload
    finally:
        con.close()


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    event_payload = collect_event_payload(payload)
    if event_payload is not None and DB.exists():
        con = sqlite3.connect(str(DB), timeout=2.0)
        try:
            con.execute(
                "INSERT INTO cockpit_events(kind, payload, created_at) VALUES(?,?,?)",
                (
                    "turn_end",
                    json.dumps(event_payload, ensure_ascii=True),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            con.commit()
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    print("{}")


if __name__ == "__main__":
    main()
