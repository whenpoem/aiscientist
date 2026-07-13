"""Snapshot and counterfactual-replay tools.

Snapshot reaches into the failures and contradictions submodules to assemble
its full payload; replay branches are stored in their own table without
touching ``mem_nodes`` or ``mem_bt_ratings``.

Snapshot scope spans both trunks (architecture.md §13): empirical-side
``mem_nodes`` plus the proof trunk's ``prv_corpus_problems``,
``prv_diagnostic_manifests``, and ``prv_lean_attempts``. Reads against
``prv_*`` are wrapped in ``OperationalError`` so v3.0-only DBs (no proof
schema yet) snapshot cleanly with empty proof sections.
"""

from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from memory_mcp.db import _connect, tx

from ._common import _emit_event, _rows_to_dicts
from .failures import _find_contradictions, _recent_failures


def _replay_id() -> str:
    return f"replay_{uuid4().hex[:12]}"


def _graph_snapshot(con) -> tuple[list[dict], list[dict]]:
    nodes = con.execute(
        """
        SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
        FROM mem_nodes
        ORDER BY created_at ASC, node_id ASC
        """
    ).fetchall()
    edges = con.execute(
        """
        SELECT edge_id, src, dst, relation, rationale, created_at
        FROM mem_edges
        ORDER BY created_at ASC, edge_id ASC
        """
    ).fetchall()
    return _rows_to_dicts(nodes), _rows_to_dicts(edges)


def _proof_snapshot(con) -> dict:
    """Read proof-trunk state into the snapshot payload.

    Wraps every read in ``sqlite3.OperationalError`` so a v3.0-only DB
    (where the prv_* tables haven't been bootstrapped yet) snapshots
    cleanly with empty proof sections.
    """
    try:
        proof_corpus_count = int(
            con.execute("SELECT COUNT(*) FROM prv_corpus_problems").fetchone()[0]
        )
    except sqlite3.OperationalError:
        proof_corpus_count = 0

    try:
        proof_drafts = _rows_to_dicts(
            con.execute(
                """
                SELECT node_id, text, state, parent_id, created_at, created_by
                FROM mem_nodes
                WHERE kind = 'proof_skeleton' AND state = 'active'
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
        )
    except sqlite3.OperationalError:
        proof_drafts = []

    try:
        proof_manifests = _rows_to_dicts(
            con.execute(
                """
                SELECT manifest_id, draft_id, status, created_at
                FROM prv_diagnostic_manifests
                ORDER BY manifest_id DESC
                LIMIT 50
                """
            ).fetchall()
        )
    except sqlite3.OperationalError:
        proof_manifests = []

    try:
        proof_lean_attempts = _rows_to_dicts(
            con.execute(
                """
                SELECT attempt_id, proposition_id, status, duration_sec, created_at
                FROM prv_lean_attempts
                ORDER BY attempt_id DESC
                LIMIT 50
                """
            ).fetchall()
        )
    except sqlite3.OperationalError:
        proof_lean_attempts = []

    return {
        "proof_corpus_count": proof_corpus_count,
        "proof_drafts": proof_drafts,
        "proof_manifests": proof_manifests,
        "proof_lean_attempts": proof_lean_attempts,
    }


def snapshot(label: str = "") -> dict:
    """Persist a point-in-time snapshot of the graph, failures, and contradiction summary.

    Includes the proof trunk's frontier (proposition + proof_skeleton
    nodes) and prv_* aggregates so a counterfactual replay against a
    proof-side branch can reconstruct enough context. Reads against
    prv_* fall back to empty for legacy v3.0-only databases.
    """
    snapshot_id = f"snap_{uuid4().hex[:12]}"
    with tx() as con:
        nodes, edges = _graph_snapshot(con)
        frontier = _rows_to_dicts(
            con.execute(
                """
                SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
                FROM mem_nodes
                WHERE state = 'active' AND kind IN ('question', 'hypothesis', 'proposition')
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
        )
        contradictions = _find_contradictions(con)
        failures = _recent_failures(con)
        paper_count = int(con.execute("SELECT COUNT(*) FROM mem_lit_compressed").fetchone()[0])
        judgement_count = int(con.execute("SELECT COUNT(*) FROM mem_judgements").fetchone()[0])
        proof = _proof_snapshot(con)
        payload = {
            "nodes": nodes,
            "edges": edges,
            "active_frontier": frontier,
            "contradictions": contradictions,
            "recent_failures": failures,
            "proof_drafts": proof["proof_drafts"],
            "proof_manifests": proof["proof_manifests"],
            "proof_lean_attempts": proof["proof_lean_attempts"],
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "active_frontier": len(frontier),
                "contradictions": len(contradictions),
                "recent_failures": len(failures),
                "papers": paper_count,
                "judgements": judgement_count,
                "proof_corpus": proof["proof_corpus_count"],
                "proof_drafts": len(proof["proof_drafts"]),
                "proof_manifests": len(proof["proof_manifests"]),
                "proof_lean_attempts": len(proof["proof_lean_attempts"]),
            },
        }
        con.execute(
            "INSERT INTO mem_snapshots(snapshot_id, label, payload) VALUES(?,?,?)",
            (snapshot_id, label, json.dumps(payload, ensure_ascii=True)),
        )
        _emit_event(
            con,
            "snapshot_created",
            {"snapshot_id": snapshot_id, "label": label, "counts": payload["counts"]},
        )
    return {"snapshot_id": snapshot_id, "label": label, "counts": payload["counts"]}


def replay_counterfactual(snapshot_id: str, counterfactual: str) -> dict:
    """Create a what-if branch from a recorded snapshot.

    Does **not** mutate ``mem_nodes`` / ``mem_bt_ratings``. Stores the
    branch metadata in ``mem_replay_branches`` and emits
    ``replay_branch_created``. The caller can then run the counterfactual
    in a sandboxed session and feed the result back via interventions.
    """
    counterfactual = counterfactual.strip()
    if not counterfactual:
        raise ValueError("counterfactual must be non-empty")
    branch_id = _replay_id()
    with tx() as con:
        snapshot_row = con.execute(
            "SELECT snapshot_id, label, payload FROM mem_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if snapshot_row is None:
            raise ValueError(f"unknown snapshot: {snapshot_id}")
        try:
            payload = json.loads(snapshot_row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        frontier = payload.get("active_frontier") or []
        divergence = {
            "snapshot_label": snapshot_row["label"],
            "frontier_size": len(frontier),
            "counterfactual": counterfactual,
        }
        con.execute(
            """
            INSERT INTO mem_replay_branches(
              branch_id, parent_snapshot_id, counterfactual, divergence_payload
            ) VALUES(?,?,?,?)
            """,
            (
                branch_id,
                snapshot_id,
                counterfactual,
                json.dumps(divergence, ensure_ascii=True),
            ),
        )
        _emit_event(
            con,
            "replay_branch_created",
            {
                "branch_id": branch_id,
                "snapshot_id": snapshot_id,
                "counterfactual": counterfactual,
            },
        )
    return {
        "branch_id": branch_id,
        "snapshot_id": snapshot_id,
        "counterfactual": counterfactual,
        "divergence": divergence,
    }


def list_snapshots(limit: int = 20) -> list[dict]:
    """Return recent snapshot metadata without loading full frozen payloads."""
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT snapshot_id, label, payload, created_at
            FROM mem_snapshots
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (min(200, max(1, int(limit))),),
        ).fetchall()
    finally:
        con.close()
    snapshots: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        counts = payload.get("counts")
        snapshots.append(
            {
                "snapshot_id": row["snapshot_id"],
                "label": row["label"],
                "created_at": row["created_at"],
                "counts": counts if isinstance(counts, dict) else {},
            }
        )
    return snapshots


def list_replay_branches(limit: int = 20) -> list[dict]:
    """Return recent replay branches, newest first."""
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT branch_id, parent_snapshot_id, counterfactual,
                   divergence_payload, created_at
            FROM mem_replay_branches
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    finally:
        con.close()
    out: list[dict] = []
    for row in rows:
        try:
            divergence = json.loads(row["divergence_payload"])
        except (TypeError, json.JSONDecodeError):
            divergence = {}
        out.append(
            {
                "branch_id": row["branch_id"],
                "parent_snapshot_id": row["parent_snapshot_id"],
                "counterfactual": row["counterfactual"],
                "divergence": divergence,
                "created_at": row["created_at"],
            }
        )
    return out
