"""Bradley-Terry ranking tools and the underlying batch MAP fit.

Contains the canonical BT comparison primitive (`_bt_apply_comparison`) plus
the public judging, posterior-comparison, ranking, pause, resume, and
information-gain tools that exercise it.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from dataclasses import dataclass

import numpy as np

from memory_mcp.db import _connect, tx

from ._common import _emit_event, _get_node

AUTO_PRUNE_ENV = "RESEARCH_AGENT_AUTO_PRUNE"

BT_STRENGTH_CLIP = 12.0
BT_PRIOR_VAR = 1.0
BT_MIN_VAR = 1e-4
BT_FIT_TOL = 1e-10
BT_FIT_MAX_ITER = 100
BT_MIN_COMPARISONS_FOR_RANK = 3
BT_PROBABILITY_SAMPLES = 8192
BT_VALID_SOURCES = {
    "llm_judge",
    "metric_diff",
    "user_intervention",
    "reviewer_critic",
}

# Kinds that may participate in a BT comparison. Cross-kind comparison is
# forbidden to keep semantics clean (architecture.md §13, ADR 0008).
BT_RANKABLE_KINDS = ("hypothesis", "proof_skeleton")


@dataclass(frozen=True)
class _BTFitResult:
    theta: np.ndarray
    covariance: np.ndarray
    counts: np.ndarray
    converged: bool
    iterations: int


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _bt_sigmoid(diff: float) -> float:
    clipped = max(-30.0, min(30.0, diff))
    return 1.0 / (1.0 + math.exp(-clipped))


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


def _fit_bt_arrays_with_state(
    node_ids: list[str],
    comparisons: list[tuple[str, str, float]],
) -> _BTFitResult:
    """Fit the joint MAP model without depending on SQLite.

    The database tool and the deterministic calibration simulator share this
    primitive so the simulator measures the exact model used in production.
    The returned covariance is centred because only pairwise strength
    differences are identifiable in a Bradley-Terry model.
    """
    if not node_ids:
        empty_float = np.zeros(0, dtype=float)
        return _BTFitResult(
            theta=empty_float,
            covariance=np.zeros((0, 0), dtype=float),
            counts=np.zeros(0, dtype=int),
            converged=True,
            iterations=0,
        )
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("node_ids must be unique")

    index = {node_id: idx for idx, node_id in enumerate(node_ids)}
    theta = np.zeros(len(node_ids), dtype=float)
    counts = np.zeros(len(node_ids), dtype=int)
    prior_precision = 1.0 / BT_PRIOR_VAR

    for winner_id, loser_id, weight in comparisons:
        if winner_id not in index or loser_id not in index:
            raise ValueError("comparison contains a node outside node_ids")
        if winner_id == loser_id:
            raise ValueError("comparison winner and loser must differ")
        if not math.isfinite(float(weight)) or float(weight) <= 0:
            raise ValueError("comparison weight must be positive and finite")
        counts[index[winner_id]] += 1
        counts[index[loser_id]] += 1

    def gradient_and_precision(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        gradient = -prior_precision * values
        precision = np.eye(len(node_ids), dtype=float) * prior_precision
        for winner_id, loser_id, raw_weight in comparisons:
            winner = index[winner_id]
            loser = index[loser_id]
            weight = float(raw_weight)
            probability = _bt_sigmoid(float(values[winner] - values[loser]))
            residual = weight * (1.0 - probability)
            fisher = weight * probability * (1.0 - probability)
            gradient[winner] += residual
            gradient[loser] -= residual
            precision[winner, winner] += fisher
            precision[loser, loser] += fisher
            precision[winner, loser] -= fisher
            precision[loser, winner] -= fisher
        return gradient, precision

    def log_posterior(values: np.ndarray) -> float:
        total = -0.5 * prior_precision * float(values @ values)
        for winner_id, loser_id, raw_weight in comparisons:
            diff = float(values[index[winner_id]] - values[index[loser_id]])
            total += float(raw_weight) * -float(np.logaddexp(0.0, -diff))
        return total

    previous_objective = log_posterior(theta)
    iterations = 0
    for iteration in range(1, BT_FIT_MAX_ITER + 1):
        gradient, precision = gradient_and_precision(theta)
        try:
            raw_step = np.linalg.solve(precision, gradient)
        except np.linalg.LinAlgError:
            raw_step = np.linalg.pinv(precision) @ gradient

        scale = 1.0
        accepted_theta = theta
        accepted_objective = previous_objective
        while scale >= 2.0**-20:
            candidate = np.clip(
                theta + scale * raw_step,
                -BT_STRENGTH_CLIP,
                BT_STRENGTH_CLIP,
            )
            candidate_objective = log_posterior(candidate)
            if candidate_objective >= previous_objective - 1e-12:
                accepted_theta = candidate
                accepted_objective = candidate_objective
                break
            scale *= 0.5
        else:
            raise RuntimeError("Bradley-Terry MAP line search failed")

        step = accepted_theta - theta
        theta = accepted_theta
        iterations = iteration
        objective_change = abs(accepted_objective - previous_objective)
        previous_objective = accepted_objective
        if float(np.max(np.abs(step))) < BT_FIT_TOL or objective_change < BT_FIT_TOL:
            break
    else:
        raise RuntimeError("Bradley-Terry MAP fit did not converge")

    _, precision = gradient_and_precision(theta)
    try:
        covariance = np.linalg.inv(precision)
    except np.linalg.LinAlgError:
        covariance = np.linalg.pinv(precision)
    centerer = np.eye(len(node_ids), dtype=float) - (
        np.ones((len(node_ids), len(node_ids)), dtype=float) / len(node_ids)
    )
    return _BTFitResult(
        theta=theta,
        covariance=centerer @ covariance @ centerer,
        counts=counts,
        converged=True,
        iterations=iterations,
    )


def _fit_bt_arrays(
    node_ids: list[str],
    comparisons: list[tuple[str, str, float]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compatibility wrapper shared by the deterministic simulator."""
    result = _fit_bt_arrays_with_state(node_ids, comparisons)
    return result.theta, result.covariance, result.counts


def _fit_bt_kind(
    con: sqlite3.Connection,
    kind: str,
) -> tuple[dict[str, tuple[float, float, int]], _BTFitResult]:
    """Refit one rankable kind from its complete comparison ledger.

    A zero-centred Gaussian prior makes the model identifiable even when the
    comparison graph is disconnected. Newton updates solve the joint MAP
    problem, then the inverse observed precision supplies marginal variances
    for an explicitly approximate Laplace posterior interval.
    """
    rows = con.execute(
        """
        SELECT r.node_id
        FROM mem_bt_ratings r
        JOIN mem_nodes n ON n.node_id = r.node_id
        WHERE n.kind = ?
        ORDER BY r.node_id
        """,
        (kind,),
    ).fetchall()
    node_ids = [str(row["node_id"]) for row in rows]
    if not node_ids:
        empty = _fit_bt_arrays_with_state([], [])
        return {}, empty

    comparison_rows = con.execute(
        """
        SELECT c.winner_id, c.loser_id, c.weight
        FROM mem_bt_comparisons c
        JOIN mem_nodes w ON w.node_id = c.winner_id
        JOIN mem_nodes l ON l.node_id = c.loser_id
        WHERE w.kind = ? AND l.kind = ?
        ORDER BY c.comparison_id
        """,
        (kind, kind),
    ).fetchall()

    comparisons = [
        (
            str(row["winner_id"]),
            str(row["loser_id"]),
            float(row["weight"]),
        )
        for row in comparison_rows
    ]
    fit = _fit_bt_arrays_with_state(node_ids, comparisons)
    fitted: dict[str, tuple[float, float, int]] = {}
    for idx, node_id in enumerate(node_ids):
        variance = max(BT_MIN_VAR, float(fit.covariance[idx, idx]))
        fitted[node_id] = (float(fit.theta[idx]), variance, int(fit.counts[idx]))
        con.execute(
            """
            UPDATE mem_bt_ratings
            SET strength = ?, strength_var = ?, n_comparisons = ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE node_id = ?
            """,
            (*fitted[node_id], node_id),
        )
    con.execute(
        """
        INSERT INTO mem_bt_fit_state(
          kind, node_order_json, covariance_json, comparison_count,
          converged, iterations, fit_error, fitted_at
        ) VALUES(?,?,?,?,1,?,'',CURRENT_TIMESTAMP)
        ON CONFLICT(kind) DO UPDATE SET
          node_order_json = excluded.node_order_json,
          covariance_json = excluded.covariance_json,
          comparison_count = excluded.comparison_count,
          converged = 1,
          iterations = excluded.iterations,
          fit_error = '',
          fitted_at = CURRENT_TIMESTAMP
        """,
        (
            kind,
            json.dumps(node_ids, ensure_ascii=True),
            json.dumps(fit.covariance.tolist(), ensure_ascii=True),
            len(comparisons),
            fit.iterations,
        ),
    )
    return fitted, fit


def _record_bt_fit_failure(
    con: sqlite3.Connection,
    *,
    kind: str,
    error: Exception,
) -> dict:
    node_ids = [
        str(row["node_id"])
        for row in con.execute(
            """
            SELECT r.node_id
            FROM mem_bt_ratings r
            JOIN mem_nodes n ON n.node_id = r.node_id
            WHERE n.kind = ?
            ORDER BY r.node_id
            """,
            (kind,),
        ).fetchall()
    ]
    comparison_count = int(
        con.execute(
            """
            SELECT COUNT(*)
            FROM mem_bt_comparisons c
            JOIN mem_nodes w ON w.node_id = c.winner_id
            JOIN mem_nodes l ON l.node_id = c.loser_id
            WHERE w.kind = ? AND l.kind = ?
            """,
            (kind, kind),
        ).fetchone()[0]
    )
    error_text = str(error)[:500]
    con.execute(
        """
        INSERT INTO mem_bt_fit_state(
          kind, node_order_json, covariance_json, comparison_count,
          converged, iterations, fit_error, fitted_at
        ) VALUES(?,?,?, ?,0,0,?,CURRENT_TIMESTAMP)
        ON CONFLICT(kind) DO UPDATE SET
          comparison_count = excluded.comparison_count,
          converged = 0,
          iterations = 0,
          fit_error = excluded.fit_error,
          fitted_at = CURRENT_TIMESTAMP
        """,
        (
            kind,
            json.dumps(node_ids, ensure_ascii=True),
            "[]",
            comparison_count,
            error_text,
        ),
    )
    payload = {
        "kind": kind,
        "comparison_count": comparison_count,
        "converged": False,
        "error": error_text,
        "ratings_preserved": True,
    }
    _emit_event(con, "bt_fit_failed", payload)
    return payload


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
    if (
        not isinstance(weight, (int, float))
        or not math.isfinite(float(weight))
        or weight <= 0
    ):
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

    _ensure_bt_row(con, winner_id)
    _ensure_bt_row(con, loser_id)

    cur = con.execute(
        """
        INSERT INTO mem_bt_comparisons(
          winner_id, loser_id, weight, source, provenance_id
        ) VALUES(?,?,?,?,?)
        """,
        (winner_id, loser_id, float(weight), source, provenance_id),
    )
    comparison_id = int(cur.lastrowid)
    try:
        fitted, fit = _fit_bt_kind(con, str(winner_kind))
    except (RuntimeError, np.linalg.LinAlgError) as exc:
        failure = _record_bt_fit_failure(
            con,
            kind=str(winner_kind),
            error=exc,
        )
        winner_rating = _ensure_bt_row(con, winner_id)
        loser_rating = _ensure_bt_row(con, loser_id)
        return {
            "comparison_id": comparison_id,
            "fit": failure,
            "winner": {
                "node_id": winner_id,
                "strength": round(float(winner_rating["strength"]), 6),
                "strength_var": round(float(winner_rating["strength_var"]), 6),
            },
            "loser": {
                "node_id": loser_id,
                "strength": round(float(loser_rating["strength"]), 6),
                "strength_var": round(float(loser_rating["strength_var"]), 6),
            },
        }
    new_theta_w, new_var_w, _ = fitted[winner_id]
    new_theta_l, new_var_l, _ = fitted[loser_id]
    fit_state = _load_fit_state(con, str(winner_kind))
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
        "fit": {
            "kind": str(winner_kind),
            "comparison_count": (
                int(fit_state["comparison_count"]) if fit_state else 0
            ),
            "converged": fit.converged,
            "iterations": fit.iterations,
        },
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


def _load_fit_state(con: sqlite3.Connection, kind: str) -> dict | None:
    row = con.execute(
        """
        SELECT kind, node_order_json, covariance_json, comparison_count,
               converged, iterations, fit_error, fitted_at
        FROM mem_bt_fit_state
        WHERE kind = ?
        """,
        (kind,),
    ).fetchone()
    if row is None:
        return None
    node_order = json.loads(str(row["node_order_json"]))
    covariance = np.asarray(json.loads(str(row["covariance_json"])), dtype=float)
    return {
        "kind": str(row["kind"]),
        "node_order": [str(node_id) for node_id in node_order],
        "covariance": covariance,
        "comparison_count": int(row["comparison_count"]),
        "converged": bool(row["converged"]),
        "iterations": int(row["iterations"]),
        "fit_error": str(row["fit_error"]),
        "fitted_at": str(row["fitted_at"]),
    }


def _probability_best_by_node(
    con: sqlite3.Connection,
    *,
    kind: str,
    eligible_node_ids: list[str],
) -> tuple[dict[str, float | None], dict | None]:
    fit_state = _load_fit_state(con, kind)
    unavailable = {node_id: None for node_id in eligible_node_ids}
    if fit_state is None or not fit_state["node_order"]:
        return unavailable, fit_state

    node_order = fit_state["node_order"]
    covariance = fit_state["covariance"]
    if covariance.shape != (len(node_order), len(node_order)):
        return unavailable, fit_state
    index = {node_id: idx for idx, node_id in enumerate(node_order)}
    selected = [node_id for node_id in eligible_node_ids if node_id in index]
    if not selected:
        return unavailable, fit_state
    if len(selected) == 1:
        return {**unavailable, selected[0]: 1.0}, fit_state

    rating_rows = con.execute(
        f"""
        SELECT node_id, strength
        FROM mem_bt_ratings
        WHERE node_id IN ({','.join('?' for _ in selected)})
        """,
        selected,
    ).fetchall()
    strengths = {str(row["node_id"]): float(row["strength"]) for row in rating_rows}
    selected_indices = [index[node_id] for node_id in selected]
    means = np.asarray([strengths[node_id] for node_id in selected], dtype=float)
    selected_covariance = covariance[np.ix_(selected_indices, selected_indices)]
    seed_material = (
        f"{kind}|{fit_state['comparison_count']}|{'|'.join(selected)}".encode("utf-8")
    )
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    samples = rng.multivariate_normal(
        means,
        selected_covariance,
        size=BT_PROBABILITY_SAMPLES,
        check_valid="ignore",
    )
    winners = np.argmax(samples, axis=1)
    counts = np.bincount(winners, minlength=len(selected))
    probabilities = {
        node_id: float(counts[idx] / BT_PROBABILITY_SAMPLES)
        for idx, node_id in enumerate(selected)
    }
    return {**unavailable, **probabilities}, fit_state


# ---------- public tools ----------


def judge_hypotheses(
    hypothesis_a_id: str,
    hypothesis_b_id: str,
    criteria: list[str] | None = None,
) -> dict:
    """Build a pairwise judging prompt for BT hypothesis selection."""
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
    """Store a pairwise judgement and update ranking scores.

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
    """Record one pairwise comparison and refit the complete BT ledger.

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

    Each row carries a 95% *approximate posterior* interval derived from a
    Laplace approximation at the joint MAP fit. The legacy ``lcb`` / ``ucb``
    field names remain for compatibility; they are not calibrated frequentist
    confidence bounds. Nodes whose comparison count is below
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
        eligible_ids = [
            str(row["node_id"])
            for row in con.execute(
                f"""
                SELECT r.node_id
                FROM mem_bt_ratings r
                JOIN mem_nodes n ON n.node_id = r.node_id
                WHERE r.status IN ({placeholders})
                  AND n.kind = ?
                  AND n.state = 'active'
                ORDER BY r.node_id
                """,
                (*statuses, kind),
            ).fetchall()
        ]
        probability_best, fit_state = _probability_best_by_node(
            con,
            kind=kind,
            eligible_node_ids=eligible_ids,
        )
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
                "interval_level": 0.95,
                "interval_kind": "laplace_credible",
                "interval_method": "laplace_map_centered_approximate_posterior",
                "interval_calibrated": False,
                "probability_best": (
                    round(float(probability_best[str(row["node_id"])]), 6)
                    if probability_best[str(row["node_id"])] is not None
                    else None
                ),
                "probability_best_method": "laplace_monte_carlo",
                "probability_best_calibrated": False,
                "fit_converged": bool(fit_state["converged"]) if fit_state else None,
                "fit_comparison_count": (
                    int(fit_state["comparison_count"]) if fit_state else 0
                ),
                "n_comparisons": int(row["n_comparisons"]),
                "elo_score": float(row["elo_score"] or 1500.0),
                "last_updated": row["last_updated"],
                "insufficient_samples": int(row["n_comparisons"]) < BT_MIN_COMPARISONS_FOR_RANK,
            }
        )
    return leaderboard


def compare_bt_candidates(a_node_id: str, b_node_id: str) -> dict:
    """Return the approximate posterior contrast between two candidates.

    The calculation uses the full centred covariance from the latest joint
    Laplace-MAP fit. The probability and interval are approximate posterior
    summaries, not calibrated frequentist guarantees.
    """
    if a_node_id == b_node_id:
        raise ValueError("a_node_id and b_node_id must differ")
    con = _connect()
    try:
        a_node = _get_node(con, a_node_id)
        b_node = _get_node(con, b_node_id)
        if a_node is None or b_node is None:
            missing = a_node_id if a_node is None else b_node_id
            raise ValueError(f"unknown BT candidate: {missing}")
        a_kind = str(a_node["kind"])
        b_kind = str(b_node["kind"])
        if a_kind not in BT_RANKABLE_KINDS or b_kind not in BT_RANKABLE_KINDS:
            raise ValueError(f"BT candidates must have kinds in {BT_RANKABLE_KINDS}")
        if a_kind != b_kind:
            raise ValueError("BT candidate comparison forbids cross-kind contrasts")

        fit_state = _load_fit_state(con, a_kind)
        if fit_state is None:
            raise RuntimeError(f"no Bradley-Terry fit state is available for {a_kind}")
        node_order = fit_state["node_order"]
        covariance = fit_state["covariance"]
        index = {node_id: idx for idx, node_id in enumerate(node_order)}
        if a_node_id not in index or b_node_id not in index:
            raise RuntimeError("latest Bradley-Terry fit does not contain both candidates")
        if covariance.shape != (len(node_order), len(node_order)):
            raise RuntimeError("latest Bradley-Terry covariance is unavailable")

        rating_rows = con.execute(
            """
            SELECT node_id, strength
            FROM mem_bt_ratings
            WHERE node_id IN (?, ?)
            """,
            (a_node_id, b_node_id),
        ).fetchall()
        strengths = {str(row["node_id"]): float(row["strength"]) for row in rating_rows}
        a_idx = index[a_node_id]
        b_idx = index[b_node_id]
        difference = strengths[a_node_id] - strengths[b_node_id]
        difference_variance = max(
            BT_MIN_VAR,
            float(
                covariance[a_idx, a_idx]
                + covariance[b_idx, b_idx]
                - 2.0 * covariance[a_idx, b_idx]
            ),
        )
        difference_sd = math.sqrt(difference_variance)
        z_score = difference / difference_sd
        probability = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
        radius = 1.96 * difference_sd
        return {
            "a_node_id": a_node_id,
            "b_node_id": b_node_id,
            "kind": a_kind,
            "strength_difference_a_minus_b": round(difference, 6),
            "difference_variance": round(difference_variance, 6),
            "credible_interval_95": [
                round(difference - radius, 6),
                round(difference + radius, 6),
            ],
            "probability_a_beats_b": round(probability, 6),
            "interval_kind": "laplace_credible",
            "posterior_method": "laplace_map_centered_approximate_posterior",
            "posterior_calibrated": False,
            "fit_converged": bool(fit_state["converged"]),
            "fit_comparison_count": int(fit_state["comparison_count"]),
            "fit_error": str(fit_state["fit_error"]),
        }
    finally:
        con.close()


def suggest_pause_low_strength(
    ucb_threshold: float,
    min_comparisons: int = 6,
    kind: str | None = None,
) -> dict:
    """Compatibility-only UCB suggestion; never changes branch state.

    This legacy heuristic remains available to old callers, but it is always
    advisory even when ``RESEARCH_AGENT_AUTO_PRUNE`` is set. New callers should
    use :func:`suggest_pause_low_probability`, which is the only BT path allowed
    to perform an automatic pause.

    ``kind`` filters which BT-rankable kinds participate. ``None`` (default)
    walks both ``hypothesis`` and ``proof_skeleton`` so the proof-trunk
    tournament is auto-prunable too. Pass an explicit kind to scope to one
    trunk.
    """
    min_n = max(1, int(min_comparisons))
    auto = False
    suggested: list[dict] = []

    if kind is not None and kind not in BT_RANKABLE_KINDS:
        raise ValueError(
            f"suggest_pause_low_strength kind must be in {BT_RANKABLE_KINDS} or None; "
            f"got {kind!r}"
        )
    target_kinds = (kind,) if kind is not None else BT_RANKABLE_KINDS
    placeholders = ",".join("?" for _ in target_kinds)

    with tx() as con:
        rows = con.execute(
            f"""
            SELECT r.node_id, r.strength, r.strength_var, r.n_comparisons,
                   r.status, n.kind, n.text
            FROM mem_bt_ratings r
            JOIN mem_nodes n ON n.node_id = r.node_id
            WHERE r.status = 'active'
              AND n.kind IN ({placeholders})
              AND n.state = 'active'
              AND r.n_comparisons >= ?
            """,
            (*target_kinds, min_n),
        ).fetchall()

        for row in rows:
            strength = float(row["strength"])
            sd = math.sqrt(max(BT_MIN_VAR, float(row["strength_var"])))
            ucb = strength + 1.96 * sd
            if ucb >= float(ucb_threshold):
                continue
            payload = {
                "node_id": row["node_id"],
                "kind": row["kind"],
                "text": row["text"],
                "strength": round(strength, 6),
                "ucb": round(ucb, 6),
                "ucb_threshold": float(ucb_threshold),
                "n_comparisons": int(row["n_comparisons"]),
                "auto_prune": auto,
            }
            suggested.append(payload)
            _emit_event(con, "branch_pause_suggested", payload)

    return {
        "auto_prune": auto,
        "deprecated": True,
        "deprecation_message": (
            "suggest_pause_low_strength is advisory-only; use "
            "suggest_pause_low_probability for posterior-based auto-pause"
        ),
        "ucb_threshold": float(ucb_threshold),
        "min_comparisons": min_n,
        "suggested": suggested,
        "paused": [],
    }


def suggest_pause_low_probability(
    max_probability_best: float = 0.05,
    min_comparisons: int = 6,
    kind: str | None = None,
) -> dict:
    """Suggest, and optionally apply, posterior-probability branch pauses.

    ``probability_best`` comes from deterministic Monte Carlo draws from the
    latest joint Laplace approximation. It is explicitly uncalibrated. The
    function is dry-run unless ``RESEARCH_AGENT_AUTO_PRUNE`` is truthy; this is
    the only BT pause-suggestion API that honors that environment flag.
    """
    threshold = float(max_probability_best)
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("max_probability_best must be between 0 and 1")
    min_n = max(1, int(min_comparisons))
    if kind is not None and kind not in BT_RANKABLE_KINDS:
        raise ValueError(
            f"suggest_pause_low_probability kind must be in {BT_RANKABLE_KINDS} "
            f"or None; got {kind!r}"
        )
    target_kinds = (kind,) if kind is not None else BT_RANKABLE_KINDS
    auto = _auto_prune_enabled()
    suggested: list[dict] = []
    paused: list[dict] = []

    with tx() as con:
        for target_kind in target_kinds:
            rows = con.execute(
                """
                SELECT r.node_id, r.strength, r.n_comparisons, r.status,
                       n.kind, n.text
                FROM mem_bt_ratings r
                JOIN mem_nodes n ON n.node_id = r.node_id
                WHERE r.status = 'active'
                  AND n.kind = ?
                  AND n.state = 'active'
                ORDER BY r.node_id
                """,
                (target_kind,),
            ).fetchall()
            node_ids = [str(row["node_id"]) for row in rows]
            probabilities, fit_state = _probability_best_by_node(
                con,
                kind=target_kind,
                eligible_node_ids=node_ids,
            )
            for row in rows:
                node_id = str(row["node_id"])
                probability = probabilities[node_id]
                if probability is None or int(row["n_comparisons"]) < min_n:
                    continue
                if float(probability) > threshold:
                    continue
                payload = {
                    "node_id": node_id,
                    "kind": str(row["kind"]),
                    "text": str(row["text"]),
                    "strength": round(float(row["strength"]), 6),
                    "probability_best": round(float(probability), 6),
                    "max_probability_best": threshold,
                    "probability_method": "laplace_monte_carlo",
                    "probability_calibrated": False,
                    "fit_converged": (
                        bool(fit_state["converged"]) if fit_state else None
                    ),
                    "fit_comparison_count": (
                        int(fit_state["comparison_count"]) if fit_state else 0
                    ),
                    "n_comparisons": int(row["n_comparisons"]),
                    "auto_prune": auto,
                }
                suggested.append(payload)
                _emit_event(con, "branch_pause_suggested", payload)
                if auto:
                    con.execute(
                        "UPDATE mem_bt_ratings SET status = 'paused' WHERE node_id = ?",
                        (node_id,),
                    )
                    paused.append(payload)
                    _emit_event(con, "branch_paused", payload)

    return {
        "auto_prune": auto,
        "max_probability_best": threshold,
        "min_comparisons": min_n,
        "probability_method": "laplace_monte_carlo",
        "probability_calibrated": False,
        "suggested": suggested,
        "paused": paused,
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
