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
    bt_strength: float | None = None
    bt_strength_var: float | None = None
    bt_n_comparisons: int = 0
    bt_status: str = "active"


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


def fetch_dashboard() -> dict[str, Any]:
    con = _connect()
    try:
        node_counts = con.execute(
            """
            SELECT
              SUM(CASE WHEN kind = 'hypothesis' AND state = 'active' THEN 1 ELSE 0 END)
                AS active_hypotheses,
              SUM(CASE WHEN state = 'refuted' THEN 1 ELSE 0 END) AS refuted_nodes,
              COUNT(*) AS nodes
            FROM mem_nodes
            """
        ).fetchone()
        failure_count = int(con.execute("SELECT COUNT(*) FROM mem_failures").fetchone()[0])
        event_row = con.execute(
            "SELECT COUNT(*) AS n, MAX(created_at) AS latest FROM cockpit_events"
        ).fetchone()
        intervention_count = int(
            con.execute("SELECT COUNT(*) FROM cockpit_interventions").fetchone()[0]
        )
        claim_count = int(con.execute("SELECT COUNT(*) FROM ver_metric_pins").fetchone()[0])
        unstable_seed_runs = 0
        if _table_exists(con, "ver_seed_runs"):
            unstable_seed_runs = int(
                con.execute(
                    "SELECT COUNT(*) FROM ver_seed_runs WHERE verdict = 'unstable'"
                ).fetchone()[0]
            )
        heldout_rows = con.execute(
            """
            SELECT dataset, budget_total, budget_used,
                   budget_total - budget_used AS remaining
            FROM ver_heldout_budgets
            ORDER BY remaining ASC, dataset ASC
            LIMIT 3
            """
        ).fetchall()
    finally:
        con.close()

    claims = fetch_claims()
    risks = fetch_risks(claims=claims)
    unverified_claims = sum(1 for claim in claims if not claim.get("verified"))
    return {
        "nodes": int(node_counts["nodes"] or 0),
        "active_hypotheses": int(node_counts["active_hypotheses"] or 0),
        "refuted_nodes": int(node_counts["refuted_nodes"] or 0),
        "failures": failure_count,
        "events": int(event_row["n"] or 0),
        "interventions": intervention_count,
        "pinned_claims": claim_count,
        "unverified_claims": unverified_claims,
        "unstable_seed_runs": unstable_seed_runs,
        "heldout_budgets": [dict(row) for row in heldout_rows],
        "latest_event_at": event_row["latest"],
        "risks": len(risks),
    }


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
        bt_rows: list[sqlite3.Row] = []
        if _table_exists(con, "mem_bt_ratings"):
            bt_rows = con.execute(
                """
                SELECT node_id, strength, strength_var, n_comparisons, status
                FROM mem_bt_ratings
                """
            ).fetchall()
    finally:
        con.close()

    parent_by_child = {
        row["dst"]: row["src"]
        for row in edge_rows
        if row["relation"] == "parent_of"
    }
    bt_by_node = {row["node_id"]: row for row in bt_rows}
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
            bt_strength=(
                float(bt_by_node[row["node_id"]]["strength"])
                if row["node_id"] in bt_by_node
                else None
            ),
            bt_strength_var=(
                float(bt_by_node[row["node_id"]]["strength_var"])
                if row["node_id"] in bt_by_node
                else None
            ),
            bt_n_comparisons=(
                int(bt_by_node[row["node_id"]]["n_comparisons"])
                if row["node_id"] in bt_by_node
                else 0
            ),
            bt_status=(
                str(bt_by_node[row["node_id"]]["status"])
                if row["node_id"] in bt_by_node
                else "active"
            ),
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


def fetch_heldout_budgets() -> list[dict[str, Any]]:
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT dataset, heldout_path, manifest_sha256, budget_total, budget_used,
                   budget_total - budget_used AS remaining, registered_at
            FROM ver_heldout_budgets
            ORDER BY remaining ASC, dataset ASC
            """
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        con.close()


def fetch_risks(
    *,
    claims: list[dict[str, Any]] | None = None,
    failures: list[dict[str, Any]] | None = None,
    graph: GraphSnapshot | None = None,
    heldout_budgets: list[dict[str, Any]] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    claims = fetch_claims() if claims is None else claims
    failures = fetch_failures() if failures is None else failures
    graph = fetch_graph() if graph is None else graph
    heldout_budgets = (
        fetch_heldout_budgets() if heldout_budgets is None else heldout_budgets
    )

    risks: list[dict[str, Any]] = []
    for claim in claims:
        verdict = str(claim.get("seed_verdict") or "pending")
        if verdict == "unstable":
            risks.append(
                {
                    "severity": "high",
                    "category": "seed",
                    "item": str(claim.get("metric", "-")),
                    "summary": (
                        f"{claim.get('metric', '-')}={claim.get('value', '-')} "
                        "has unstable seed verification"
                    ),
                }
            )
        elif not claim.get("verified"):
            risks.append(
                {
                    "severity": "medium",
                    "category": "claim",
                    "item": str(claim.get("metric", "-")),
                    "summary": (
                        f"{claim.get('metric', '-')}={claim.get('value', '-')} "
                        f"needs verification ({claim.get('seeds', '0/3')})"
                    ),
                }
            )

    for failure in failures:
        seen_count = int(failure.get("seen_count") or 0)
        if seen_count >= 3:
            risks.append(
                {
                    "severity": "medium" if seen_count < 8 else "high",
                    "category": "failure",
                    "item": f"#{failure.get('failure_id', '-')}",
                    "summary": (
                        f"{failure.get('trigger', '-')} repeated {seen_count} times: "
                        f"{failure.get('symptom', '-')}"
                    ),
                }
            )

    for edge in graph.edges:
        if edge.get("relation") == "contradicts":
            risks.append(
                {
                    "severity": "high",
                    "category": "contradiction",
                    "item": str(edge.get("edge_id", "-")),
                    "summary": f"{edge.get('src', '-')} contradicts {edge.get('dst', '-')}",
                }
            )

    for budget in heldout_budgets:
        remaining = int(budget.get("remaining") or 0)
        if remaining <= 1:
            risks.append(
                {
                    "severity": "high" if remaining <= 0 else "medium",
                    "category": "heldout",
                    "item": str(budget.get("dataset", "-")),
                    "summary": (
                        f"{budget.get('dataset', '-')} held-out budget "
                        f"{budget.get('budget_used', 0)}/{budget.get('budget_total', 0)}"
                    ),
                }
            )

    severity_order = {"high": 0, "medium": 1, "low": 2}
    risks.sort(key=lambda row: (severity_order.get(str(row["severity"]), 9), row["category"]))
    return risks[: max(1, limit)]


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


# ---------------------------------------------------------------------------
# Proof-trunk readers (G3 / v4.1.0a0). All three are tolerant of databases
# that pre-date v4.0 (where the prv_* tables don't exist) — they return an
# empty list instead of raising. The TUI renders an "empty" placeholder row
# in that case rather than a panic message.
# ---------------------------------------------------------------------------


def fetch_corpus_problems(limit: int = 200) -> list[dict[str, Any]]:
    """Read recent proof-corpus problems for the Corpus tab.

    Joins keyword counts in a single query so each row carries lex / sem
    counts the table can render directly. Statement is left full-length
    here; the pane truncates for display.
    """
    con = _connect()
    try:
        if not _table_exists(con, "prv_corpus_problems"):
            return []
        rows = con.execute(
            """
            SELECT
              p.problem_id,
              p.source,
              p.statement,
              p.reference_proof,
              p.domain_tags,
              p.ingested_at,
              SUM(CASE WHEN k.kind = 'lexical' THEN 1 ELSE 0 END) AS n_lexical,
              SUM(CASE WHEN k.kind = 'semantic' THEN 1 ELSE 0 END) AS n_semantic
            FROM prv_corpus_problems p
            LEFT JOIN prv_corpus_keywords k ON k.problem_id = p.problem_id
            GROUP BY p.problem_id
            ORDER BY p.ingested_at DESC, p.problem_id ASC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        domain_tags = _parse_payload(row["domain_tags"])
        # domain_tags JSON is a list, but _parse_payload returns dicts. Re-parse
        # explicitly so we get the list shape stored on disk.
        try:
            tags = json.loads(row["domain_tags"]) if row["domain_tags"] else []
        except (json.JSONDecodeError, TypeError):
            tags = domain_tags if isinstance(domain_tags, list) else []
        if not isinstance(tags, list):
            tags = []
        out.append(
            {
                "problem_id": row["problem_id"],
                "source": row["source"],
                "statement": row["statement"] or "",
                "reference_proof": row["reference_proof"] or "",
                "domain_tags": [str(tag) for tag in tags],
                "primary_domain": str(tags[0]) if tags else "",
                "ingested_at": row["ingested_at"],
                "n_lexical": int(row["n_lexical"] or 0),
                "n_semantic": int(row["n_semantic"] or 0),
            }
        )
    return out


def fetch_diagnostic_manifests(limit: int = 100) -> list[dict[str, Any]]:
    """Read recent diagnostic manifests for the Diagnostics tab.

    Parses ``items_json`` once here so the renderer can show snippet count
    + flawed count without re-parsing per render. Older 'closed' status
    values are normalized to 'applied' / 'empty' depending on flaw count
    (defensive — current schema only emits the three known states).
    """
    con = _connect()
    try:
        if not _table_exists(con, "prv_diagnostic_manifests"):
            return []
        rows = con.execute(
            """
            SELECT manifest_id, draft_id, status, items_json,
                   created_at, finalized_at
            FROM prv_diagnostic_manifests
            ORDER BY manifest_id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        items = _parse_payload(row["items_json"])
        entries = items.get("entries") if isinstance(items, dict) else None
        if not isinstance(entries, list):
            entries = []
        flawed = sum(1 for e in entries if isinstance(e, dict) and e.get("is_flawed"))
        out.append(
            {
                "manifest_id": int(row["manifest_id"]),
                "draft_id": row["draft_id"],
                "status": row["status"],
                "snippet_count": len(entries),
                "flawed_count": flawed,
                "entries": entries,
                "created_at": row["created_at"],
                "finalized_at": row["finalized_at"],
            }
        )
    return out


def fetch_lean_attempts(limit: int = 200) -> list[dict[str, Any]]:
    """Read recent Lean attempts for the Lean tab.

    Returns rows in newest-first order. The Lean source body and full
    stderr are included so the detail-pane drill-in renders without a
    second DB hit.
    """
    con = _connect()
    try:
        if not _table_exists(con, "prv_lean_attempts"):
            return []
        rows = con.execute(
            """
            SELECT attempt_id, proposition_id, status, lean_source, stderr,
                   duration_sec, triage_eligible, triage_difficulty,
                   triage_reasons, created_at
            FROM prv_lean_attempts
            ORDER BY attempt_id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            reasons = json.loads(row["triage_reasons"]) if row["triage_reasons"] else []
        except (json.JSONDecodeError, TypeError):
            reasons = []
        if not isinstance(reasons, list):
            reasons = []
        out.append(
            {
                "attempt_id": int(row["attempt_id"]),
                "proposition_id": row["proposition_id"],
                "status": row["status"],
                "lean_source": row["lean_source"] or "",
                "stderr": row["stderr"] or "",
                "duration_sec": (
                    float(row["duration_sec"]) if row["duration_sec"] is not None else None
                ),
                "triage_eligible": bool(row["triage_eligible"]),
                "triage_difficulty": row["triage_difficulty"],
                "triage_reasons": [str(r) for r in reasons],
                "created_at": row["created_at"],
            }
        )
    return out


def fetch_new_events(last_event_id: int = 0, limit: int = 2000) -> list[dict[str, Any]]:
    con = _connect()
    try:
        if last_event_id <= 0:
            rows = con.execute(
                """
                SELECT id, kind, payload, created_at
                FROM (
                    SELECT id, kind, payload, created_at
                    FROM cockpit_events
                    ORDER BY id DESC
                    LIMIT ?
                ) recent
                ORDER BY id ASC
                """,
                (max(1, limit),),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT id, kind, payload, created_at
                FROM cockpit_events
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (last_event_id, max(1, limit)),
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


def refute_node(node_id: str, reason: str) -> dict[str, Any]:
    from memory_mcp import impl as memory_impl

    return memory_impl.mark_refuted(node_id, reason)


def pin_metric_local(
    *,
    claim: str,
    value: str,
    session_id: str,
    source_command: str = "",
    note: str = "",
) -> dict[str, Any]:
    from verify_mcp import impl as verify_impl

    return verify_impl.pin_metric(
        claim=claim,
        value=value,
        session_id=session_id,
        source_command=source_command,
        note=note,
    )
