"""Tool implementations for memory_mcp."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from uuid import uuid4

from claudescientist.runtime import emit_cockpit_event

from .db import _connect, bootstrap, tx

TOOL_NAMES = [
    "propose_hypothesis",
    "attach_evidence",
    "mark_refuted",
    "get_active_frontier",
    "get_ancestors",
    "judge_hypotheses",
    "record_judgement",
    "record_failure",
    "match_signatures",
    "find_contradictions",
    "snapshot",
    "ingest_paper",
    "query_literature",
    "find_baselines_for",
    "update_bt_rating",
    "get_bt_leaderboard",
    "suggest_pause_low_strength",
    "resume_branch",
    "expected_information_gain",
    "record_calibration",
    "calibration_report",
    "replay_counterfactual",
    "list_replay_branches",
]

CALIBRATION_BUCKETS = (0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95)

AUTO_PRUNE_ENV = "RESEARCH_AGENT_AUTO_PRUNE"

BT_STRENGTH_CLIP = 12.0
BT_PRIOR_VAR = 1.0
BT_LEARNING_RATE = 0.5
BT_MIN_VAR = 1e-4
BT_MIN_COMPARISONS_FOR_RANK = 3
BT_VALID_SOURCES = {
    "llm_judge",
    "metric_diff",
    "user_intervention",
    "reviewer_critic",
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def _node_id(kind: str) -> str:
    prefix = {
        "hypothesis": "hyp",
        "evidence": "ev",
        "question": "q",
        "experiment": "exp",
        "conclusion": "con",
    }.get(kind, "node")
    return f"{prefix}_{uuid4().hex[:12]}"


def _signature(trigger: str, symptom: str, root_cause: str, resolution: str) -> str:
    parts = [trigger, symptom, root_cause, resolution]
    return " | ".join(part.strip().lower() for part in parts if part and part.strip())


def _fts_query(text: str) -> str:
    tokens = [token.lower() for token in _TOKEN_RE.findall(text)]
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens[:12])


def _emit_event(con, kind: str, payload: dict) -> None:
    try:
        emit_cockpit_event(con, kind, payload)
    except sqlite3.Error:
        return


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


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


def _recent_failures(con, limit: int = 25) -> list[dict]:
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


def _get_node(con: sqlite3.Connection, node_id: str) -> sqlite3.Row | None:
    return con.execute(
        """
        SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
        FROM mem_nodes
        WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _bt_sigmoid(diff: float) -> float:
    clipped = max(-30.0, min(30.0, diff))
    return 1.0 / (1.0 + math.exp(-clipped))


def _bt_clip_strength(value: float) -> float:
    return max(-BT_STRENGTH_CLIP, min(BT_STRENGTH_CLIP, value))


def _ensure_bt_row(con: sqlite3.Connection, node_id: str) -> sqlite3.Row:
    row = con.execute(
        """
        SELECT node_id, strength, strength_var, n_comparisons, status
        FROM mem_bt_ratings WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    if row is not None:
        return row
    con.execute(
        "INSERT OR IGNORE INTO mem_bt_ratings(node_id) VALUES(?)",
        (node_id,),
    )
    return con.execute(
        """
        SELECT node_id, strength, strength_var, n_comparisons, status
        FROM mem_bt_ratings WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()


def _bt_online_update(
    theta_w: float,
    var_w: float,
    theta_l: float,
    var_l: float,
    weight: float = 1.0,
) -> tuple[float, float, float, float]:
    """One online Bradley-Terry update via Laplace approximation.

    Uses logistic-link gradient ascent on log-likelihood for the means and
    a Fisher-information posterior precision update for the variances. The
    Beta(1,1)-equivalent shrinkage comes from BT_PRIOR_VAR initial variance
    plus the strength clip.
    """
    weight_eff = max(0.05, float(weight))
    p_winner = _bt_sigmoid(theta_w - theta_l)
    fisher = max(1e-6, p_winner * (1.0 - p_winner)) * weight_eff
    delta = BT_LEARNING_RATE * weight_eff * (1.0 - p_winner)
    new_theta_w = _bt_clip_strength(theta_w + delta)
    new_theta_l = _bt_clip_strength(theta_l - delta)
    new_var_w = 1.0 / (1.0 / max(var_w, BT_MIN_VAR) + fisher)
    new_var_l = 1.0 / (1.0 / max(var_l, BT_MIN_VAR) + fisher)
    return new_theta_w, max(BT_MIN_VAR, new_var_w), new_theta_l, max(BT_MIN_VAR, new_var_l)


def _bt_apply_comparison(
    con: sqlite3.Connection,
    *,
    winner_id: str,
    loser_id: str,
    weight: float,
    source: str,
    provenance_id: int | None,
) -> dict:
    if source not in BT_VALID_SOURCES:
        raise ValueError(f"unsupported BT source: {source!r}")
    if winner_id == loser_id:
        raise ValueError("winner_id and loser_id must differ")
    if not isinstance(weight, (int, float)) or weight <= 0 or math.isnan(float(weight)):
        raise ValueError("weight must be a positive finite number")

    winner_node = _get_node(con, winner_id)
    loser_node = _get_node(con, loser_id)
    if winner_node is None:
        raise ValueError(f"unknown winner node: {winner_id}")
    if loser_node is None:
        raise ValueError(f"unknown loser node: {loser_id}")
    if winner_node["kind"] != "hypothesis" or loser_node["kind"] != "hypothesis":
        raise ValueError("BT comparisons require hypothesis nodes")

    winner_row = _ensure_bt_row(con, winner_id)
    loser_row = _ensure_bt_row(con, loser_id)
    new_theta_w, new_var_w, new_theta_l, new_var_l = _bt_online_update(
        float(winner_row["strength"]),
        float(winner_row["strength_var"]),
        float(loser_row["strength"]),
        float(loser_row["strength_var"]),
        weight=float(weight),
    )

    cur = con.execute(
        """
        INSERT INTO mem_bt_comparisons(
          winner_id, loser_id, weight, source, provenance_id
        ) VALUES(?,?,?,?,?)
        """,
        (winner_id, loser_id, float(weight), source, provenance_id),
    )
    comparison_id = int(cur.lastrowid)
    con.execute(
        """
        UPDATE mem_bt_ratings
        SET strength = ?, strength_var = ?,
            n_comparisons = n_comparisons + 1,
            last_updated = CURRENT_TIMESTAMP
        WHERE node_id = ?
        """,
        (new_theta_w, new_var_w, winner_id),
    )
    con.execute(
        """
        UPDATE mem_bt_ratings
        SET strength = ?, strength_var = ?,
            n_comparisons = n_comparisons + 1,
            last_updated = CURRENT_TIMESTAMP
        WHERE node_id = ?
        """,
        (new_theta_l, new_var_l, loser_id),
    )
    _emit_event(
        con,
        "bt_rating_updated",
        {
            "comparison_id": comparison_id,
            "winner_id": winner_id,
            "loser_id": loser_id,
            "source": source,
            "weight": float(weight),
            "winner_strength": round(new_theta_w, 6),
            "loser_strength": round(new_theta_l, 6),
        },
    )
    return {
        "comparison_id": comparison_id,
        "winner": {
            "node_id": winner_id,
            "strength": round(new_theta_w, 6),
            "strength_var": round(new_var_w, 6),
        },
        "loser": {
            "node_id": loser_id,
            "strength": round(new_theta_l, 6),
            "strength_var": round(new_var_l, 6),
        },
    }


def _find_contradictions(con) -> list[dict]:
    explicit_rows = con.execute(
        """
        SELECT e.edge_id, e.src, src.kind AS src_kind, src.text AS src_text, src.state AS src_state,
               e.dst, dst.kind AS dst_kind, dst.text AS dst_text, dst.state AS dst_state,
               e.rationale, e.created_at
        FROM mem_edges e
        JOIN mem_nodes src ON src.node_id = e.src
        JOIN mem_nodes dst ON dst.node_id = e.dst
        WHERE e.relation = 'contradicts'
        ORDER BY e.created_at DESC, e.edge_id DESC
        """
    ).fetchall()
    evidence_rows = con.execute(
        """
        SELECT n.node_id, n.kind, n.text, n.state,
               SUM(CASE WHEN e.relation = 'supports' THEN 1 ELSE 0 END) AS support_count,
               SUM(CASE WHEN e.relation = 'refutes' THEN 1 ELSE 0 END) AS refute_count,
               MAX(e.created_at) AS last_edge_at
        FROM mem_nodes n
        JOIN mem_edges e ON e.dst = n.node_id
        JOIN mem_nodes ev ON ev.node_id = e.src
        WHERE e.relation IN ('supports', 'refutes')
          AND ev.kind = 'evidence'
          AND ev.state = 'active'
        GROUP BY n.node_id, n.kind, n.text, n.state
        HAVING support_count > 0 AND refute_count > 0
        ORDER BY last_edge_at DESC, n.node_id DESC
        """
    ).fetchall()

    contradictions: list[dict] = []
    for row in explicit_rows:
        contradictions.append(
            {
                "type": "explicit_edge",
                "edge_id": row["edge_id"],
                "src_id": row["src"],
                "src_kind": row["src_kind"],
                "src_text": row["src_text"],
                "src_state": row["src_state"],
                "dst_id": row["dst"],
                "dst_kind": row["dst_kind"],
                "dst_text": row["dst_text"],
                "dst_state": row["dst_state"],
                "rationale": row["rationale"] or "",
                "created_at": row["created_at"],
            }
        )

    for row in evidence_rows:
        evidence = con.execute(
            """
            SELECT ev.node_id, ev.text, e.relation, e.created_at
            FROM mem_edges e
            JOIN mem_nodes ev ON ev.node_id = e.src
            WHERE e.dst = ?
              AND e.relation IN ('supports', 'refutes')
              AND ev.kind = 'evidence'
              AND ev.state = 'active'
            ORDER BY e.created_at DESC, ev.node_id DESC
            LIMIT 8
            """,
            (row["node_id"],),
        ).fetchall()
        contradictions.append(
            {
                "type": "evidence_conflict",
                "node_id": row["node_id"],
                "kind": row["kind"],
                "text": row["text"],
                "state": row["state"],
                "support_count": int(row["support_count"]),
                "refute_count": int(row["refute_count"]),
                "evidence": _rows_to_dicts(evidence),
                "created_at": row["last_edge_at"],
            }
        )

    return contradictions


def propose_hypothesis(text: str, parent_id: str | None = None, rationale: str = "") -> dict:
    """Create a new hypothesis node and optionally connect it to a parent."""
    node_id = _node_id("hypothesis")
    with tx() as con:
        if parent_id:
            parent = con.execute(
                "SELECT node_id FROM mem_nodes WHERE node_id = ?",
                (parent_id,),
            ).fetchone()
            if parent is None:
                raise ValueError(f"Unknown parent node: {parent_id}")
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by, parent_id)
            VALUES(?,?,?,?,?,?)
            """,
            (node_id, "hypothesis", text, "active", "claude", parent_id),
        )
        con.execute("INSERT OR IGNORE INTO mem_bt_ratings(node_id) VALUES(?)", (node_id,))
        if parent_id:
            con.execute(
                "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
                (parent_id, node_id, "parent_of", rationale),
            )
            con.execute(
                "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
                (parent_id, node_id, "refines", rationale),
            )
        _emit_event(con, "graph_delta", {"node_id": node_id, "kind": "hypothesis", "text": text})
    return {"node_id": node_id}


def attach_evidence(node_id: str, evidence_text: str, polarity: str) -> dict:
    """Create an evidence node and connect it to a target hypothesis."""
    if polarity not in {"supports", "refutes"}:
        raise ValueError("polarity must be one of: supports, refutes")
    evidence_id = _node_id("evidence")
    with tx() as con:
        target = con.execute(
            "SELECT node_id FROM mem_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if target is None:
            raise ValueError(f"Unknown node: {node_id}")
        con.execute(
            """
            INSERT INTO mem_nodes(node_id, kind, text, state, created_by, parent_id)
            VALUES(?,?,?,?,?,?)
            """,
            (evidence_id, "evidence", evidence_text, "active", "claude", node_id),
        )
        con.execute(
            "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
            (node_id, evidence_id, "parent_of", evidence_text),
        )
        con.execute(
            "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
            (evidence_id, node_id, polarity, evidence_text),
        )
        _emit_event(
            con,
            "graph_delta",
            {"node_id": evidence_id, "kind": "evidence", "text": evidence_text},
        )
    return {"evidence_id": evidence_id}


def mark_refuted(node_id: str, reason: str, evidence_ids: list[str] | None = None) -> dict:
    """Mark an existing node as refuted."""
    with tx() as con:
        cur = con.execute(
            "UPDATE mem_nodes SET state = 'refuted' WHERE node_id = ?",
            (node_id,),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown node: {node_id}")
        _emit_event(
            con,
            "graph_delta",
            {
                "node_id": node_id,
                "kind": "refuted",
                "text": reason,
                "evidence_ids": evidence_ids or [],
            },
        )
    return {"node_id": node_id, "state": "refuted"}


def get_active_frontier() -> list[dict]:
    """Return active question and hypothesis nodes ordered by recency."""
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
            FROM mem_nodes
            WHERE state = 'active' AND kind IN ('question', 'hypothesis')
            ORDER BY created_at DESC
            LIMIT 50
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def get_ancestors(node_id: str) -> list[dict]:
    """Return a node plus its ancestors up to the root."""
    con = _connect()
    try:
        chain: list[dict] = []
        current = node_id
        while current:
            row = con.execute(
                """
                SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
                FROM mem_nodes
                WHERE node_id = ?
                """,
                (current,),
            ).fetchone()
            if row is None:
                break
            item = dict(row)
            chain.append(item)
            current = item["parent_id"]
        return chain
    finally:
        con.close()


def judge_hypotheses(
    hypothesis_a_id: str,
    hypothesis_b_id: str,
    criteria: list[str] | None = None,
) -> dict:
    """Build a pairwise judging prompt for Elo-based hypothesis selection."""
    criteria = criteria or ["novelty", "feasibility", "falsifiability"]
    con = _connect()
    try:
        a_row = _get_node(con, hypothesis_a_id)
        b_row = _get_node(con, hypothesis_b_id)
        if a_row is None:
            raise ValueError(f"Unknown hypothesis: {hypothesis_a_id}")
        if b_row is None:
            raise ValueError(f"Unknown hypothesis: {hypothesis_b_id}")
        if a_row["kind"] != "hypothesis" or b_row["kind"] != "hypothesis":
            raise ValueError("judge_hypotheses only supports hypothesis nodes")
        prompt = (
            "You are ranking two research hypotheses for the next experiment.\n"
            "Compare them in order by: "
            + ", ".join(criteria)
            + ".\n"
            'Return strict JSON with keys "winner_id" and "reason".\n\n'
            f"Hypothesis A ({a_row['node_id']}): {a_row['text']}\n"
            f"Hypothesis B ({b_row['node_id']}): {b_row['text']}\n"
        )
        return {
            "hypothesis_a": dict(a_row),
            "hypothesis_b": dict(b_row),
            "criteria": criteria,
            "prompt": prompt,
        }
    finally:
        con.close()


def record_judgement(
    a_node_id: str,
    b_node_id: str,
    winner_node_id: str,
    reason: str = "",
    k_factor: float = 32.0,
) -> dict:
    """Store a pairwise judgement and update Elo scores."""
    if winner_node_id not in {a_node_id, b_node_id}:
        raise ValueError("winner_node_id must match one of the compared nodes")
    if k_factor <= 0:
        raise ValueError("k_factor must be positive")

    with tx() as con:
        a_row = _get_node(con, a_node_id)
        b_row = _get_node(con, b_node_id)
        if a_row is None:
            raise ValueError(f"Unknown hypothesis: {a_node_id}")
        if b_row is None:
            raise ValueError(f"Unknown hypothesis: {b_node_id}")
        if a_row["kind"] != "hypothesis" or b_row["kind"] != "hypothesis":
            raise ValueError("record_judgement only supports hypothesis nodes")

        rating_a = float(a_row["elo_score"])
        rating_b = float(b_row["elo_score"])
        expected_a = _expected_score(rating_a, rating_b)
        expected_b = _expected_score(rating_b, rating_a)
        score_a = 1.0 if winner_node_id == a_node_id else 0.0
        score_b = 1.0 if winner_node_id == b_node_id else 0.0
        new_rating_a = rating_a + (k_factor * (score_a - expected_a))
        new_rating_b = rating_b + (k_factor * (score_b - expected_b))

        cur = con.execute(
            """
            INSERT INTO mem_judgements(
              a_node_id, b_node_id, winner_node_id, reason, k_factor
            ) VALUES(?,?,?,?,?)
            """,
            (a_node_id, b_node_id, winner_node_id, reason.strip(), float(k_factor)),
        )
        judgement_id = int(cur.lastrowid)
        con.execute(
            "UPDATE mem_nodes SET elo_score = ? WHERE node_id = ?",
            (new_rating_a, a_node_id),
        )
        con.execute(
            "UPDATE mem_nodes SET elo_score = ? WHERE node_id = ?",
            (new_rating_b, b_node_id),
        )
        loser_id = b_node_id if winner_node_id == a_node_id else a_node_id
        _bt_apply_comparison(
            con,
            winner_id=winner_node_id,
            loser_id=loser_id,
            weight=1.0,
            source="llm_judge",
            provenance_id=None,
        )
        _emit_event(
            con,
            "judgement_recorded",
            {
                "judgement_id": judgement_id,
                "a_node_id": a_node_id,
                "b_node_id": b_node_id,
                "winner_node_id": winner_node_id,
            },
        )
    return {
        "judgement_id": judgement_id,
        "winner_node_id": winner_node_id,
        "scores": {
            a_node_id: round(new_rating_a, 6),
            b_node_id: round(new_rating_b, 6),
        },
    }


def record_failure(trigger: str, symptom: str, root_cause: str = "", resolution: str = "") -> dict:
    """Store a failure signature for later matching."""
    signature = _signature(trigger, symptom, root_cause, resolution)
    with tx() as con:
        cur = con.execute(
            """
            INSERT INTO mem_failures(
              trigger, symptom, root_cause, resolution, signature,
              seen_count, first_seen, last_seen
            )
            VALUES(?,?,?,?,?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            """,
            (trigger, symptom, root_cause, resolution, signature),
        )
        failure_id = int(cur.lastrowid)
        _emit_event(
            con,
            "failure_added",
            {"failure_id": failure_id, "trigger": trigger, "symptom": symptom},
        )
    return {"failure_id": failure_id}


def match_signatures(situation: str, k: int = 5) -> list[dict]:
    """FTS search prior failures ranked by BM25 relevance."""
    query = _fts_query(situation)
    if not query:
        return []
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT f.failure_id, f.trigger, f.symptom, f.root_cause, f.resolution,
                   f.signature, f.seen_count, f.first_seen, f.last_seen,
                   bm25(mem_failures_fts) AS bm25_score
            FROM mem_failures f
            JOIN mem_failures_fts ON mem_failures_fts.rowid = f.failure_id
            WHERE mem_failures_fts MATCH ?
            ORDER BY bm25_score
            LIMIT ?
            """,
            (query, max(1, k)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def find_contradictions() -> list[dict]:
    """Return places where the graph contains explicit or evidence-level conflicts."""
    con = _connect()
    try:
        return _find_contradictions(con)
    finally:
        con.close()


def snapshot(label: str = "") -> dict:
    """Persist a point-in-time snapshot of the graph, failures, and contradiction summary."""
    snapshot_id = f"snap_{uuid4().hex[:12]}"
    with tx() as con:
        nodes, edges = _graph_snapshot(con)
        frontier = _rows_to_dicts(
            con.execute(
                """
                SELECT node_id, kind, text, state, elo_score, created_at, created_by, parent_id
                FROM mem_nodes
                WHERE state = 'active' AND kind IN ('question', 'hypothesis')
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
        )
        contradictions = _find_contradictions(con)
        failures = _recent_failures(con)
        paper_count = int(con.execute("SELECT COUNT(*) FROM mem_lit_compressed").fetchone()[0])
        judgement_count = int(con.execute("SELECT COUNT(*) FROM mem_judgements").fetchone()[0])
        payload = {
            "nodes": nodes,
            "edges": edges,
            "active_frontier": frontier,
            "contradictions": contradictions,
            "recent_failures": failures,
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "active_frontier": len(frontier),
                "contradictions": len(contradictions),
                "recent_failures": len(failures),
                "papers": paper_count,
                "judgements": judgement_count,
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


def ingest_paper(paper_id: str, source: str, structured: dict) -> dict:
    """Store a compressed paper produced by the librarian."""
    if source not in {"arxiv", "openalex", "manual"}:
        raise ValueError("source must be one of: arxiv, openalex, manual")
    authors = structured.get("authors", [])
    relates_to = structured.get("relates_to", {})
    with tx() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO mem_lit_compressed(
              paper_id, source, title, authors, year, venue, problem, method,
              claimed_results, assumptions, limitations, trust_level, relates_to,
              raw_abstract, ingested_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """,
            (
                paper_id,
                source,
                structured.get("title", ""),
                json.dumps(authors, ensure_ascii=True),
                structured.get("year"),
                structured.get("venue", ""),
                structured.get("problem", ""),
                structured.get("method", ""),
                structured.get("claimed_results", ""),
                structured.get("assumptions", ""),
                structured.get("limitations", ""),
                structured.get("trust_level", 0.5),
                json.dumps(relates_to, ensure_ascii=True),
                structured.get("raw_abstract", ""),
            ),
        )
        _emit_event(
            con,
            "literature_ingested",
            {
                "paper_id": paper_id,
                "source": source,
                "title": structured.get("title", ""),
            },
        )
    return {"ingested": paper_id}


def query_literature(question: str, k: int = 10) -> list[dict]:
    """Return literature ranked by BM25 and trust level."""
    query = _fts_query(question)
    con = _connect()
    try:
        if not query:
            rows = con.execute(
                """
                SELECT paper_id, title, problem, method, claimed_results,
                       assumptions, limitations, trust_level, 0.0 AS bm25_score
                FROM mem_lit_compressed
                ORDER BY trust_level DESC, ingested_at DESC
                LIMIT ?
                """,
                (max(1, k),),
            ).fetchall()
            return [dict(row) for row in rows]
        rows = con.execute(
            """
            SELECT p.paper_id, p.title, p.problem, p.method, p.claimed_results,
                   p.assumptions, p.limitations, p.trust_level,
                   bm25(mem_lit_fts) AS bm25_score
            FROM mem_lit_compressed p
            JOIN mem_lit_fts ON mem_lit_fts.rowid = p.rowid
            WHERE mem_lit_fts MATCH ?
            ORDER BY bm25_score * (1.0 / (0.5 + p.trust_level))
            LIMIT ?
            """,
            (query, max(1, k)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def find_baselines_for(method_description: str, k: int = 5) -> list[dict]:
    """Return papers whose method descriptions best match the given method."""
    return query_literature(method_description, k=k)


def update_bt_rating(
    winner_id: str,
    loser_id: str,
    source: str,
    weight: float = 1.0,
    provenance_id: int | None = None,
) -> dict:
    """Record one pairwise comparison and run an incremental BT update.

    Source must be in {llm_judge, metric_diff, user_intervention,
    reviewer_critic}. Emits ``bt_rating_updated`` and returns the updated
    strength + variance for both nodes.
    """
    with tx() as con:
        return _bt_apply_comparison(
            con,
            winner_id=winner_id,
            loser_id=loser_id,
            weight=float(weight),
            source=source,
            provenance_id=int(provenance_id) if provenance_id is not None else None,
        )


def get_bt_leaderboard(top_k: int = 20, include_paused: bool = False) -> list[dict]:
    """Return active hypotheses ordered by Bradley-Terry strength.

    Each row carries a 95% LUCB-style interval ``[lcb, ucb]`` derived from
    the Laplace posterior variance. Nodes whose ``n_comparisons`` is below
    ``BT_MIN_COMPARISONS_FOR_RANK`` get an ``insufficient_samples`` flag.
    """
    top_k = max(1, int(top_k))
    statuses = ("active", "paused") if include_paused else ("active",)
    placeholders = ",".join("?" for _ in statuses)
    con = _connect()
    try:
        rows = con.execute(
            f"""
            SELECT r.node_id, r.strength, r.strength_var, r.n_comparisons,
                   r.status, r.last_updated,
                   n.text, n.kind, n.state, n.elo_score
            FROM mem_bt_ratings r
            JOIN mem_nodes n ON n.node_id = r.node_id
            WHERE r.status IN ({placeholders})
              AND n.kind = 'hypothesis'
              AND n.state = 'active'
            ORDER BY r.strength DESC, r.n_comparisons DESC, r.node_id ASC
            LIMIT ?
            """,
            (*statuses, top_k),
        ).fetchall()
    finally:
        con.close()

    leaderboard: list[dict] = []
    for row in rows:
        var = max(BT_MIN_VAR, float(row["strength_var"]))
        sd = math.sqrt(var)
        strength = float(row["strength"])
        leaderboard.append(
            {
                "node_id": row["node_id"],
                "text": row["text"],
                "kind": row["kind"],
                "state": row["state"],
                "status": row["status"],
                "strength": round(strength, 6),
                "strength_var": round(var, 6),
                "lcb": round(strength - 1.96 * sd, 6),
                "ucb": round(strength + 1.96 * sd, 6),
                "n_comparisons": int(row["n_comparisons"]),
                "elo_score": float(row["elo_score"] or 1500.0),
                "last_updated": row["last_updated"],
                "insufficient_samples": int(row["n_comparisons"]) < BT_MIN_COMPARISONS_FOR_RANK,
            }
        )
    return leaderboard


def _auto_prune_enabled() -> bool:
    return os.environ.get(AUTO_PRUNE_ENV, "0") not in {"", "0", "false", "False"}


def suggest_pause_low_strength(
    ucb_threshold: float,
    min_comparisons: int = 6,
) -> dict:
    """Suggest pausing branches whose Bradley-Terry UCB lies below a threshold.

    By default this is **dry-run**: it only emits ``branch_pause_suggested``
    events and returns the candidates. When the ``RESEARCH_AGENT_AUTO_PRUNE``
    environment variable is truthy we additionally flip ``mem_bt_ratings.status``
    to ``paused`` and emit ``branch_paused`` events. The dry-run default keeps
    the system safe: pause is reversible via :func:`resume_branch`.
    """
    min_n = max(1, int(min_comparisons))
    auto = _auto_prune_enabled()
    suggested: list[dict] = []
    paused: list[dict] = []

    with tx() as con:
        rows = con.execute(
            """
            SELECT r.node_id, r.strength, r.strength_var, r.n_comparisons,
                   r.status, n.text
            FROM mem_bt_ratings r
            JOIN mem_nodes n ON n.node_id = r.node_id
            WHERE r.status = 'active'
              AND n.kind = 'hypothesis'
              AND n.state = 'active'
              AND r.n_comparisons >= ?
            """,
            (min_n,),
        ).fetchall()

        for row in rows:
            strength = float(row["strength"])
            sd = math.sqrt(max(BT_MIN_VAR, float(row["strength_var"])))
            ucb = strength + 1.96 * sd
            if ucb >= float(ucb_threshold):
                continue
            payload = {
                "node_id": row["node_id"],
                "text": row["text"],
                "strength": round(strength, 6),
                "ucb": round(ucb, 6),
                "ucb_threshold": float(ucb_threshold),
                "n_comparisons": int(row["n_comparisons"]),
                "auto_prune": auto,
            }
            suggested.append(payload)
            _emit_event(con, "branch_pause_suggested", payload)
            if auto:
                con.execute(
                    "UPDATE mem_bt_ratings SET status = 'paused' WHERE node_id = ?",
                    (row["node_id"],),
                )
                paused.append(payload)
                _emit_event(con, "branch_paused", payload)

    return {
        "auto_prune": auto,
        "ucb_threshold": float(ucb_threshold),
        "min_comparisons": min_n,
        "suggested": suggested,
        "paused": paused if auto else [],
    }


def resume_branch(node_id: str, reason: str) -> dict:
    """Reverse a paused/pruned branch. Used by replay or by user intervention."""
    with tx() as con:
        row = con.execute(
            "SELECT status FROM mem_bt_ratings WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown bt rating: {node_id}")
        previous = str(row["status"])
        if previous == "active":
            return {"node_id": node_id, "previous_status": previous, "status": "active"}
        con.execute(
            "UPDATE mem_bt_ratings SET status = 'active' WHERE node_id = ?",
            (node_id,),
        )
        _emit_event(
            con,
            "branch_promoted",
            {
                "node_id": node_id,
                "previous_status": previous,
                "reason": reason or "",
            },
        )
    return {"node_id": node_id, "previous_status": previous, "status": "active"}


def expected_information_gain(candidate_node_ids: list[str]) -> list[dict]:
    """Score candidate hypotheses by predicted reduction in posterior entropy.

    For each candidate we compare it against the current top hypothesis (by
    BT strength) and approximate the expected drop in posterior variance the
    next comparison would yield. High-variance underdogs score highest, which
    is what drives the experiment-selection loop in P3+.
    """
    if not candidate_node_ids:
        return []
    placeholders = ",".join("?" for _ in candidate_node_ids)
    con = _connect()
    try:
        top = con.execute(
            """
            SELECT node_id, strength, strength_var
            FROM mem_bt_ratings
            WHERE status = 'active'
            ORDER BY strength DESC
            LIMIT 1
            """
        ).fetchone()
        rows = con.execute(
            f"""
            SELECT node_id, strength, strength_var, n_comparisons
            FROM mem_bt_ratings
            WHERE node_id IN ({placeholders})
            """,
            tuple(candidate_node_ids),
        ).fetchall()
    finally:
        con.close()

    if top is None:
        return []
    ref_strength = float(top["strength"])
    ref_var = max(BT_MIN_VAR, float(top["strength_var"]))

    scored: list[dict] = []
    for row in rows:
        strength = float(row["strength"])
        var = max(BT_MIN_VAR, float(row["strength_var"]))
        diff = strength - ref_strength
        p = _bt_sigmoid(diff)
        fisher = max(1e-6, p * (1.0 - p))
        # Expected posterior variance after one comparison (Laplace).
        new_var = 1.0 / (1.0 / var + fisher)
        new_ref_var = 1.0 / (1.0 / ref_var + fisher)
        gain_self = max(0.0, var - new_var)
        gain_ref = max(0.0, ref_var - new_ref_var)
        eig = gain_self + 0.5 * gain_ref
        scored.append(
            {
                "node_id": row["node_id"],
                "ref_node_id": top["node_id"],
                "current_strength": round(strength, 6),
                "current_var": round(var, 6),
                "p_beats_ref": round(p, 6),
                "expected_information_gain": round(eig, 6),
                "n_comparisons": int(row["n_comparisons"]),
            }
        )
    scored.sort(key=lambda item: item["expected_information_gain"], reverse=True)
    return scored


def _bucket_predicted_p(value: float) -> float:
    if not (0.0 <= value <= 1.0):
        raise ValueError("predicted_p must be in [0, 1]")
    closest = min(CALIBRATION_BUCKETS, key=lambda bucket: abs(bucket - float(value)))
    return float(closest)


def record_calibration(
    agent_name: str,
    predicted_p: float,
    realized_outcome: int,
) -> dict:
    """Append one calibration data point for an agent.

    ``predicted_p`` is bucketed to the nearest CALIBRATION_BUCKETS centre so
    the reliability diagram has predictable bins. ``realized_outcome`` must
    be 0 or 1.
    """
    if realized_outcome not in (0, 1):
        raise ValueError("realized_outcome must be 0 or 1")
    if not agent_name.strip():
        raise ValueError("agent_name must be non-empty")
    bucket = _bucket_predicted_p(float(predicted_p))
    with tx() as con:
        con.execute(
            """
            INSERT INTO meta_calibration(agent_name, predicted_p, realized_outcome, n)
            VALUES(?, ?, ?, 1)
            ON CONFLICT(agent_name, predicted_p, realized_outcome) DO UPDATE SET
              n = n + 1
            """,
            (agent_name.strip(), bucket, int(realized_outcome)),
        )
    return {
        "agent_name": agent_name.strip(),
        "bucket": bucket,
        "outcome": int(realized_outcome),
    }


def calibration_report(agent_name: str | None = None) -> dict:
    """Return reliability-diagram buckets and a Brier-score summary.

    When ``agent_name`` is ``None`` the report aggregates across every agent.
    """
    where = "WHERE agent_name = ?" if agent_name else ""
    params: tuple = (agent_name.strip(),) if agent_name else ()
    con = _connect()
    try:
        rows = con.execute(
            f"""
            SELECT agent_name, predicted_p, realized_outcome, n
            FROM meta_calibration
            {where}
            ORDER BY predicted_p ASC
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    buckets: dict[float, dict[str, float]] = {}
    weighted_brier_num = 0.0
    weighted_brier_den = 0
    for row in rows:
        p = float(row["predicted_p"])
        outcome = int(row["realized_outcome"])
        n = int(row["n"])
        entry = buckets.setdefault(
            p,
            {"predicted_p": p, "n": 0, "wins": 0, "observed_p": 0.0},
        )
        entry["n"] += n
        if outcome == 1:
            entry["wins"] += n
        weighted_brier_num += n * (p - outcome) ** 2
        weighted_brier_den += n

    diagram = []
    for p in sorted(buckets):
        entry = buckets[p]
        observed = entry["wins"] / entry["n"] if entry["n"] else 0.0
        entry["observed_p"] = round(observed, 6)
        diagram.append(entry)

    drift = max(
        (abs(entry["observed_p"] - entry["predicted_p"]) for entry in diagram),
        default=0.0,
    )
    brier = (
        weighted_brier_num / weighted_brier_den if weighted_brier_den else 0.0
    )

    return {
        "agent_name": agent_name,
        "buckets": diagram,
        "brier_score": round(brier, 6),
        "max_drift": round(drift, 6),
        "total_predictions": int(weighted_brier_den),
    }


def _replay_id() -> str:
    return f"replay_{uuid4().hex[:12]}"


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
        snapshot = con.execute(
            "SELECT snapshot_id, label, payload FROM mem_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if snapshot is None:
            raise ValueError(f"unknown snapshot: {snapshot_id}")
        try:
            payload = json.loads(snapshot["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        frontier = payload.get("active_frontier") or []
        divergence = {
            "snapshot_label": snapshot["label"],
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


bootstrap()
