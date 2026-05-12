"""ClosureReport: a snapshot of every piece of evidence around a node.

The report walks the available evidence around the target node and
summarizes it in one document. The intent is "if a reviewer asks why
this proposition / hypothesis is closed, hand them this single file".
The DTO doesn't decide closed vs not — it just gathers the evidence
the reviewer needs to make that call.

For propositions: latest diagnostic manifest status, Lean attempts,
child draft chain.

For hypotheses: BT strength + rank, preregistration outcomes, pinned
metrics, seed verdicts.

For other kinds (questions, evidence): a minimal summary.
"""

from __future__ import annotations

import sqlite3

from claudescientist.runtime import connect_sqlite, now_utc_iso, state_db_path
from cockpit.export.dto.base import Report, ReportSection


def _connect() -> sqlite3.Connection:
    return connect_sqlite(state_db_path())


def _short(node_id: str) -> str:
    if "_" not in node_id:
        return node_id[:10]
    prefix, suffix = node_id.split("_", 1)
    return f"{prefix}_{suffix[:6]}"


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _fetch_node(con: sqlite3.Connection, node_id: str) -> dict | None:
    row = con.execute(
        """
        SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
        FROM mem_nodes WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _fetch_bt(con: sqlite3.Connection, node_id: str) -> dict | None:
    if not _table_exists(con, "mem_bt_ratings"):
        return None
    row = con.execute(
        """
        SELECT strength, strength_var, n_comparisons, status
        FROM mem_bt_ratings WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _fetch_child_drafts(con: sqlite3.Connection, node_id: str) -> list[dict]:
    """Recursive walk to find every proof_skeleton descendant of a proposition."""
    rows = con.execute(
        """
        WITH RECURSIVE descendants(node_id, kind, text, parent_id, depth) AS (
          SELECT node_id, kind, text, parent_id, 0
          FROM mem_nodes WHERE node_id = ?
          UNION ALL
          SELECT child.node_id, child.kind, child.text, child.parent_id, descendants.depth + 1
          FROM mem_nodes child
          JOIN descendants ON child.parent_id = descendants.node_id
        )
        SELECT node_id, kind, text, depth FROM descendants
        WHERE kind = 'proof_skeleton'
        ORDER BY depth DESC, node_id DESC
        """,
        (node_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_latest_manifest(con: sqlite3.Connection, draft_ids: list[str]) -> dict | None:
    if not _table_exists(con, "prv_diagnostic_manifests") or not draft_ids:
        return None
    placeholders = ",".join("?" for _ in draft_ids)
    row = con.execute(
        f"""
        SELECT manifest_id, draft_id, status, items_json, created_at, finalized_at
        FROM prv_diagnostic_manifests
        WHERE draft_id IN ({placeholders})
        ORDER BY manifest_id DESC
        LIMIT 1
        """,
        draft_ids,
    ).fetchone()
    return dict(row) if row is not None else None


def _fetch_lean_attempts(con: sqlite3.Connection, node_id: str) -> list[dict]:
    if not _table_exists(con, "prv_lean_attempts"):
        return []
    rows = con.execute(
        """
        SELECT attempt_id, status, duration_sec, triage_eligible, triage_difficulty,
               created_at
        FROM prv_lean_attempts
        WHERE proposition_id = ?
        ORDER BY attempt_id DESC
        LIMIT 20
        """,
        (node_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_preregs(con: sqlite3.Connection, node_id: str) -> list[dict]:
    if not _table_exists(con, "ver_preregistrations"):
        return []
    rows = con.execute(
        """
        SELECT prereg_id, metric_name AS metric, threshold, direction,
               status, locked_at, resolved_at
        FROM ver_preregistrations
        WHERE hypothesis_id = ?
        ORDER BY prereg_id DESC
        LIMIT 20
        """,
        (node_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_pinned_metrics(con: sqlite3.Connection, node_id: str) -> list[dict]:
    if not _table_exists(con, "ver_metric_pins"):
        return []
    rows = con.execute(
        """
        SELECT p.id AS pin_id, p.claim AS metric, p.value,
               p.session_id AS dataset, p.created_at AS pinned_at,
               COALESCE(
                 (
                   SELECT sr.verdict
                   FROM ver_seed_runs sr
                   WHERE sr.metric_pin_id = p.id
                   ORDER BY sr.created_at DESC, sr.run_id DESC
                   LIMIT 1
                 ),
                 'pending'
               ) AS seed_verdict
        FROM ver_metric_pins p
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT 20
        """,
    ).fetchall()
    return [dict(row) for row in rows]


def build_closure(node_id: str) -> Report:
    """Assemble a ClosureReport for the given node."""
    con = _connect()
    try:
        node = _fetch_node(con, node_id)
        if node is None:
            raise ValueError(f"unknown node: {node_id!r}")
        sections: list[ReportSection] = []

        # ---- overview -----------------------------------------------------
        overview_lines = [
            f"node id: {node['node_id']}",
            f"kind: {node['kind']}",
            f"state: {node['state']}",
            f"parent: {node['parent_id'] or '-'}",
            f"created at: {node['created_at']}",
            f"created by: {node['created_by']}",
            "",
            "text:",
            node["text"],
        ]
        sections.append(
            ReportSection(
                key="overview",
                title="Overview",
                body="\n".join(overview_lines),
                meta={"kind": node["kind"], "state": node["state"]},
            )
        )

        # ---- BT strength (only meaningful for ranked kinds) --------------
        if node["kind"] in ("hypothesis", "proof_skeleton"):
            bt = _fetch_bt(con, node_id)
            if bt is not None:
                bt_lines = [
                    f"strength: {float(bt['strength'] or 0.0):+.3f}",
                    f"variance: {float(bt['strength_var'] or 0.0):.3f}",
                    f"comparisons: {int(bt['n_comparisons'] or 0)}",
                    f"status: {bt['status']}",
                ]
                sections.append(
                    ReportSection(
                        key="bt",
                        title="Bradley-Terry rating",
                        body="\n".join(bt_lines),
                    )
                )

        # ---- propositions: draft chain + manifest + lean -----------------
        if node["kind"] == "proposition":
            drafts = _fetch_child_drafts(con, node_id)
            if drafts:
                draft_lines = [
                    f"  - {_short(d['node_id'])}  (depth {d['depth']})"
                    for d in drafts
                ]
                sections.append(
                    ReportSection(
                        key="drafts",
                        title=f"Proof drafts ({len(drafts)})",
                        body="\n".join(draft_lines),
                    )
                )
                latest = _fetch_latest_manifest(
                    con, [d["node_id"] for d in drafts]
                )
                if latest is not None:
                    manifest_lines = [
                        f"manifest id: {latest['manifest_id']}",
                        f"draft id: {latest['draft_id']}",
                        f"status: {latest['status']}",
                        f"created at: {latest['created_at']}",
                        f"finalized at: {latest['finalized_at'] or '-'}",
                    ]
                    sections.append(
                        ReportSection(
                            key="diagnostic",
                            title="Latest diagnostic manifest",
                            body="\n".join(manifest_lines),
                            meta={"status": latest["status"]},
                        )
                    )
            lean = _fetch_lean_attempts(con, node_id)
            if lean:
                lean_lines = [
                    f"  - attempt {row['attempt_id']}: {row['status']} "
                    f"(triage={row['triage_difficulty']}, "
                    f"duration={row['duration_sec'] or '-'})"
                    for row in lean
                ]
                sections.append(
                    ReportSection(
                        key="lean",
                        title=f"Lean attempts ({len(lean)})",
                        body="\n".join(lean_lines),
                    )
                )

        # ---- hypotheses: preregs + pinned metrics ------------------------
        if node["kind"] == "hypothesis":
            preregs = _fetch_preregs(con, node_id)
            if preregs:
                prereg_lines = [
                    f"  - prereg {row['prereg_id']}: {row['metric']} "
                    f"{row['direction']} {row['threshold']} → {row['status']}"
                    for row in preregs
                ]
                sections.append(
                    ReportSection(
                        key="preregistrations",
                        title=f"Preregistrations ({len(preregs)})",
                        body="\n".join(prereg_lines),
                    )
                )
            pins = _fetch_pinned_metrics(con, node_id)
            if pins:
                pin_lines = [
                    f"  - pin {row['pin_id']}: {row['metric']} = "
                    f"{row['value']} on {row['dataset']} "
                    f"(seeds: {row['seed_verdict'] or '-'})"
                    for row in pins
                ]
                sections.append(
                    ReportSection(
                        key="metrics",
                        title=f"Pinned metrics ({len(pins)})",
                        body="\n".join(pin_lines),
                    )
                )
    finally:
        con.close()

    title = f"Closure: {_short(node_id)} ({node['kind']})"
    return Report(
        kind="closure",
        node_id=node_id,
        title=title,
        generated_at=now_utc_iso(),
        sections=tuple(sections),
        metadata={"state": node["state"]},
    )
