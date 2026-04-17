"""SQLite-backed cockpit data access."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from claudescientist.runtime import connect_sqlite, now_utc_iso, state_db_path

from .db import ensure

TREE_RELATIONS = {"parent_of"}


@dataclass(slots=True)
class GraphNode:
    node_id: str
    kind: str
    text: str
    state: str
    elo_score: float
    created_at: str
    created_by: str
    parent_id: str | None


@dataclass(slots=True)
class GraphSnapshot:
    nodes: dict[str, GraphNode]
    children_by_parent: dict[str, list[str]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)

    @property
    def roots(self) -> list[str]:
        return [
            node_id
            for node_id, node in self.nodes.items()
            if node.parent_id is None
        ]

    def node(self, node_id: str | None) -> GraphNode | None:
        if node_id is None:
            return None
        return self.nodes.get(node_id)

    def parents_of(self, node_id: str) -> list[str]:
        node = self.nodes.get(node_id)
        if node is None or node.parent_id is None:
            return []
        return [node.parent_id]

    def children_of(self, node_id: str) -> list[str]:
        return list(self.children_by_parent.get(node_id, ()))

    def cross_edges_of(self, node_id: str) -> list[dict[str, Any]]:
        return [
            edge
            for edge in self.edges
            if edge["relation"] not in TREE_RELATIONS
            and (edge["src"] == node_id or edge["dst"] == node_id)
        ]

    def visible_ids(self, show_refuted: bool = False) -> list[str]:
        visible: list[str] = []
        seen: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in seen:
                return
            node = self.nodes[node_id]
            seen.add(node_id)
            if node.state == "refuted" and not show_refuted:
                for child_id in self.children_of(node_id):
                    visit(child_id)
                return
            visible.append(node_id)
            for child_id in self.children_of(node_id):
                visit(child_id)

        for root_id in self.roots:
            visit(root_id)

        for node_id in sorted(self.nodes):
            if node_id not in seen and (show_refuted or self.nodes[node_id].state != "refuted"):
                visible.append(node_id)
        return visible


def _connect() -> sqlite3.Connection:
    ensure()
    return connect_sqlite(state_db_path())


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _parse_payload(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": payload}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def fetch_counts() -> dict[str, int]:
    con = _connect()
    try:
        node_count = int(con.execute("SELECT COUNT(*) FROM mem_nodes").fetchone()[0])
        failure_count = int(con.execute("SELECT COUNT(*) FROM mem_failures").fetchone()[0])
        event_count = int(con.execute("SELECT COUNT(*) FROM cockpit_events").fetchone()[0])
        intervention_count = int(
            con.execute("SELECT COUNT(*) FROM cockpit_interventions").fetchone()[0]
        )
        return {
            "nodes": node_count,
            "failures": failure_count,
            "events": event_count,
            "interventions": intervention_count,
        }
    finally:
        con.close()


def fetch_latest_event_id() -> int:
    con = _connect()
    try:
        row = con.execute("SELECT COALESCE(MAX(id), 0) FROM cockpit_events").fetchone()
        return int(row[0] if row is not None else 0)
    finally:
        con.close()


def fetch_graph() -> GraphSnapshot:
    con = _connect()
    try:
        node_rows = con.execute(
            """
            SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
            FROM mem_nodes
            ORDER BY created_at ASC, node_id ASC
            """
        ).fetchall()
        edge_rows = con.execute(
            """
            SELECT edge_id, src, dst, relation, rationale, created_at
            FROM mem_edges
            ORDER BY created_at ASC, edge_id ASC
            """
        ).fetchall()
    finally:
        con.close()

    parent_by_child = {
        row["dst"]: row["src"]
        for row in edge_rows
        if row["relation"] == "parent_of"
    }
    nodes = {
        row["node_id"]: GraphNode(
            node_id=row["node_id"],
            kind=row["kind"],
            text=row["text"],
            state=row["state"],
            elo_score=float(row["elo_score"] or 1500.0),
            created_at=row["created_at"],
            created_by=row["created_by"],
            parent_id=parent_by_child.get(row["node_id"]) or row["parent_id"],
        )
        for row in node_rows
    }
    children_by_parent: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        if node.parent_id:
            children_by_parent.setdefault(node.parent_id, []).append(node_id)
    for child_ids in children_by_parent.values():
        child_ids.sort(key=lambda item: (nodes[item].created_at, item))
    edges = _rows_to_dicts(edge_rows)
    return GraphSnapshot(nodes=nodes, children_by_parent=children_by_parent, edges=edges)


def fetch_failures(limit: int = 100) -> list[dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT failure_id, trigger, symptom, root_cause, resolution, signature,
                   seen_count, first_seen, last_seen
            FROM mem_failures
            ORDER BY last_seen DESC, failure_id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        con.close()


def fetch_claims(limit: int = 100) -> list[dict[str, Any]]:
    con = _connect()
    try:
        seed_runs_by_pin: dict[int, dict[str, Any]] = {}
        if _table_exists(con, "ver_seed_runs"):
            seed_rows = con.execute(
                """
                SELECT metric_pin_id, COUNT(*) AS run_count,
                       AVG(mean_value) AS mean_value,
                       AVG(std_value) AS std_value,
                       MAX(verdict) AS verdict
                FROM ver_seed_runs
                WHERE metric_pin_id IS NOT NULL
                GROUP BY metric_pin_id
                """
            ).fetchall()
            seed_runs_by_pin = {int(row["metric_pin_id"]): dict(row) for row in seed_rows}

        rows = con.execute(
            """
            SELECT p.id AS pin_id, p.claim, p.value, p.provenance_id, p.session_id,
                   p.source_command, p.note, p.created_at AS pin_created_at,
                   pr.created_at AS provenance_created_at, pr.claim AS provenance_claim,
                   pr.value AS provenance_value, pr.session_id AS provenance_session_id,
                   pr.source_command AS provenance_source_command
            FROM ver_metric_pins p
            JOIN ver_provenance pr ON pr.id = p.provenance_id
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    finally:
        con.close()

    claims: list[dict[str, Any]] = []
    for row in rows:
        seed_info = seed_runs_by_pin.get(int(row["pin_id"]), {})
        run_count = int(seed_info.get("run_count") or 0)
        verdict = str(seed_info.get("verdict") or "")
        verified = run_count >= 3 and verdict == "stable"
        claims.append(
            {
                "pin_id": int(row["pin_id"]),
                "metric": row["claim"],
                "claim": row["claim"],
                "value": row["value"],
                "dataset": row["session_id"],
                "session_id": row["session_id"],
                "source_command": row["source_command"] or "",
                "note": row["note"] or "",
                "provenance_id": int(row["provenance_id"]),
                "created_at": row["pin_created_at"],
                "verified": verified,
                "seed_runs": f"{run_count}/3" if run_count else "0/3",
                "seeds": f"{run_count}/3" if run_count else "0/3",
                "seed_verdict": verdict or "pending",
                "provenance": {
                    "claim": row["provenance_claim"],
                    "value": row["provenance_value"],
                    "session_id": row["provenance_session_id"],
                    "source_command": row["provenance_source_command"] or "",
                    "created_at": row["provenance_created_at"],
                },
            }
        )
    return claims


def fetch_literature(limit: int = 100) -> list[dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT paper_id, source, title, authors, year, venue, problem, method,
                   claimed_results, assumptions, limitations, trust_level, relates_to,
                   raw_abstract, ingested_at
            FROM mem_lit_compressed
            ORDER BY ingested_at DESC, paper_id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    finally:
        con.close()

    literature: list[dict[str, Any]] = []
    for row in rows:
        task = row["problem"] or row["method"] or row["title"] or ""
        literature.append(
            {
                "paper_id": row["paper_id"],
                "source": row["source"],
                "title": row["title"] or "",
                "authors": row["authors"] or "",
                "year": row["year"],
                "venue": row["venue"] or "",
                "task": task,
                "score": float(row["trust_level"] or 0.0),
                "trust_level": float(row["trust_level"] or 0.0),
                "problem": row["problem"] or "",
                "method": row["method"] or "",
                "claimed_results": row["claimed_results"] or "",
                "assumptions": row["assumptions"] or "",
                "limitations": row["limitations"] or "",
                "relates_to": row["relates_to"] or "{}",
                "raw_abstract": row["raw_abstract"] or "",
                "created_at": row["ingested_at"],
            }
        )
    return literature


def fetch_new_events(last_event_id: int = 0, limit: int = 2000) -> list[dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT id, kind, payload, created_at
            FROM cockpit_events
            WHERE id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (max(0, last_event_id), max(1, limit)),
        ).fetchall()
    finally:
        con.close()

    events: list[dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        event["payload"] = _parse_payload(event.get("payload"))
        events.append(event)
    return events


def record_event(kind: str, payload: dict[str, Any] | str | None = None) -> int:
    con = _connect()
    payload_text = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload or {}, ensure_ascii=True)
    )
    try:
        cursor = con.execute(
            """
            INSERT INTO cockpit_events(kind, payload, created_at)
            VALUES(?,?,?)
            """,
            (kind, payload_text, now_utc_iso()),
        )
        con.commit()
        return int(cursor.lastrowid or 0)
    finally:
        con.close()


def write_intervention(kind: str, target: str | None, payload: str) -> dict[str, int]:
    cleaned_payload = payload.strip()
    con = _connect()
    try:
        cursor = con.execute(
            """
            INSERT INTO cockpit_interventions(kind, target, payload)
            VALUES(?,?,?)
            """,
            (kind, target, cleaned_payload),
        )
        intervention_id = int(cursor.lastrowid or 0)
        event_id = record_event(
            "intervention",
            {"kind": kind, "target": target, "payload": cleaned_payload},
        )
        con.commit()
        return {"intervention_id": intervention_id, "event_id": event_id}
    finally:
        con.close()
