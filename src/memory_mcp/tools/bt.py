"""Bradley-Terry ranking tools and the underlying online-update math.

Contains the canonical BT comparison primitive (`_bt_apply_comparison`) plus
the seven public tools that exercise it: judge / record_judgement /
update_bt_rating / get_bt_leaderboard / suggest_pause_low_strength /
resume_branch / expected_information_gain.
"""

from __future__ import annotations

import math
import os
import sqlite3

from memory_mcp.db import _connect, tx

from ._common import _emit_event, _get_node

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

# Kinds that may participate in a BT comparison. Cross-kind comparison is
# forbidden to keep semantics clean (architecture.md §13, ADR 0008).
BT_RANKABLE_KINDS = ("hypothesis", "proof_skeleton")


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
    winner_kind = winner_node["kind"]
    loser_kind = loser_node["kind"]
    if winner_kind not in BT_RANKABLE_KINDS or loser_kind not in BT_RANKABLE_KINDS:
        raise ValueError(
            f"BT comparisons require kinds in {BT_RANKABLE_KINDS}; "
            f"got winner={winner_kind!r}, loser={loser_kind!r}"
        )
    if winner_kind != loser_kind:
        raise ValueError(
            f"BT comparison forbids cross-kind: winner is {winner_kind!r}, "
            f"loser is {loser_kind!r}"
        )

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


def _auto_prune_enabled() -> bool:
    return os.environ.get(AUTO_PRUNE_ENV, "0") not in {"", "0", "false", "False"}


# ---------- public tools ----------


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
    """Store a pairwise judgement and update Elo scores.

    Dual-writes to the legacy Elo column (`mem_nodes.elo_score`) AND the
    new BT ledger via `_bt_apply_comparison`. New code should prefer
    :func:`update_bt_rating` for non-LLM-judge sources.
    """
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


def get_bt_leaderboard(
    top_k: int = 20,
    include_paused: bool = False,
    kind: str = "hypothesis",
) -> list[dict]:
    """Return active nodes of one ``kind`` ordered by Bradley-Terry strength.

    Default ``kind='hypothesis'`` preserves v3.0 backward compatibility.
    Pass ``kind='proof_skeleton'`` to view the proof-trunk leaderboard.
    Cross-kind leaderboards are intentionally not supported; the BT
    comparison primitive forbids cross-kind matches, so a mixed table
    would conflate unrelated rankings.

    Each row carries a 95% LUCB-style interval ``[lcb, ucb]`` derived from
    the Laplace posterior variance. Nodes whose ``n_comparisons`` is below
    ``BT_MIN_COMPARISONS_FOR_RANK`` get an ``insufficient_samples`` flag.
    """
    if kind not in BT_RANKABLE_KINDS:
        raise ValueError(
            f"get_bt_leaderboard kind must be in {BT_RANKABLE_KINDS}; got {kind!r}"
        )
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
              AND n.kind = ?
              AND n.state = 'active'
            ORDER BY r.strength DESC, r.n_comparisons DESC, r.node_id ASC
            LIMIT ?
            """,
            (*statuses, kind, top_k),
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


def expected_information_gain(
    candidate_node_ids: list[str],
    kind: str = "hypothesis",
) -> list[dict]:
    """Score candidate nodes by predicted reduction in posterior entropy.

    For each candidate we compare it against the current top node *of the
    same ``kind``* (by BT strength) and approximate the expected drop in
    posterior variance the next comparison would yield. High-variance
    underdogs score highest, which is what drives the experiment-selection
    loop in P3+.

    The ``kind`` parameter (default ``hypothesis`` for v3.0 compat) ensures
    the reference top node can actually be compared against the candidates;
    BT forbids cross-kind comparison.
    """
    if kind not in BT_RANKABLE_KINDS:
        raise ValueError(
            f"expected_information_gain kind must be in {BT_RANKABLE_KINDS}; got {kind!r}"
        )
    if not candidate_node_ids:
        return []
    placeholders = ",".join("?" for _ in candidate_node_ids)
    con = _connect()
    try:
        top = con.execute(
            """
            SELECT r.node_id, r.strength, r.strength_var
            FROM mem_bt_ratings r
            JOIN mem_nodes n ON n.node_id = r.node_id
            WHERE r.status = 'active' AND n.kind = ?
            ORDER BY r.strength DESC
            LIMIT 1
            """,
            (kind,),
        ).fetchone()
        rows = con.execute(
            f"""
            SELECT r.node_id, r.strength, r.strength_var, r.n_comparisons
            FROM mem_bt_ratings r
            JOIN mem_nodes n ON n.node_id = r.node_id
            WHERE r.node_id IN ({placeholders})
              AND n.kind = ?
            """,
            (*candidate_node_ids, kind),
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
