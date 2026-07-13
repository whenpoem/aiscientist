"""Deterministic diagnostics for the Bradley-Terry ranking contract."""

from __future__ import annotations

import math
from itertools import combinations
from typing import Sequence

import numpy as np

from memory_mcp.tools.bt import BT_MIN_VAR, _bt_sigmoid, _fit_bt_arrays


def _rate_with_standard_error(successes: int, total: int) -> dict[str, float | int]:
    rate = successes / total if total else 0.0
    standard_error = math.sqrt(rate * (1.0 - rate) / total) if total else 0.0
    return {
        "successes": int(successes),
        "total": int(total),
        "rate": round(rate, 6),
        "monte_carlo_standard_error": round(standard_error, 6),
    }


def simulate_bt_diagnostics(
    *,
    true_strengths: Sequence[float] = (-0.8, 0.0, 0.8),
    trials: int = 1000,
    comparisons_per_pair: int = 12,
    seed: int = 20260713,
    prune_threshold: float = 0.0,
    min_comparisons: int = 6,
) -> dict:
    """Measure ranking recovery, interval coverage, and false-prune frequency.

    Each trial creates a balanced round-robin ledger from known Bradley-Terry
    strengths, fits the same joint MAP model used by the MCP tool, and applies
    the same ``strength + 1.96 * sd < threshold`` pause-suggestion rule.

    Coverage is diagnostic only. It does not turn the Laplace-MAP intervals
    into calibrated confidence bounds, and the output keeps that contract
    explicit.
    """
    strengths = np.asarray(tuple(float(value) for value in true_strengths), dtype=float)
    if strengths.ndim != 1 or len(strengths) < 3:
        raise ValueError("true_strengths must contain at least three values")
    if not np.all(np.isfinite(strengths)):
        raise ValueError("true_strengths must be finite")
    if len(set(float(value) for value in strengths)) != len(strengths):
        raise ValueError("true_strengths must be distinct to score full ranking recovery")
    if int(trials) < 1:
        raise ValueError("trials must be positive")
    if int(comparisons_per_pair) < 1:
        raise ValueError("comparisons_per_pair must be positive")
    if int(min_comparisons) < 1:
        raise ValueError("min_comparisons must be positive")
    if not math.isfinite(float(prune_threshold)):
        raise ValueError("prune_threshold must be finite")

    trials = int(trials)
    comparisons_per_pair = int(comparisons_per_pair)
    min_comparisons = int(min_comparisons)
    node_ids = [f"candidate_{idx}" for idx in range(len(strengths))]
    pairs = list(combinations(range(len(strengths)), 2))
    centred_truth = strengths - float(np.mean(strengths))
    true_order = tuple(np.argsort(-centred_truth, kind="stable"))
    true_top = int(true_order[0])
    rng = np.random.default_rng(int(seed))

    top_recovered = 0
    full_order_recovered = 0
    covered = 0
    coverage_total = 0
    false_pruned = 0
    false_prune_total = 0
    correctly_pruned = 0
    true_prune_total = 0

    for _ in range(trials):
        ledger: list[tuple[str, str, float]] = []
        for left, right in pairs:
            probability_left_wins = _bt_sigmoid(float(strengths[left] - strengths[right]))
            outcomes = rng.random(comparisons_per_pair) < probability_left_wins
            for left_wins in outcomes:
                winner, loser = (left, right) if bool(left_wins) else (right, left)
                ledger.append((node_ids[winner], node_ids[loser], 1.0))

        estimates, covariance, counts = _fit_bt_arrays(node_ids, ledger)
        estimated_order = tuple(np.argsort(-estimates, kind="stable"))
        top_recovered += int(int(estimated_order[0]) == true_top)
        full_order_recovered += int(estimated_order == true_order)

        for idx in range(len(node_ids)):
            variance = max(BT_MIN_VAR, float(covariance[idx, idx]))
            radius = 1.96 * math.sqrt(variance)
            covered += int(
                float(estimates[idx]) - radius
                <= float(centred_truth[idx])
                <= float(estimates[idx]) + radius
            )
            coverage_total += 1

            if int(counts[idx]) < min_comparisons:
                continue
            suggested = float(estimates[idx]) + radius < float(prune_threshold)
            if float(centred_truth[idx]) >= float(prune_threshold):
                false_prune_total += 1
                false_pruned += int(suggested)
            else:
                true_prune_total += 1
                correctly_pruned += int(suggested)

    return {
        "contract": {
            "interval_method": "laplace_map_centered_approximate_posterior",
            "interval_level": 0.95,
            "interval_calibrated": False,
            "interpretation": (
                "Monte Carlo diagnostics for this scenario; not a universal "
                "confidence guarantee or permission to enable automatic pruning."
            ),
        },
        "scenario": {
            "true_strengths": [float(value) for value in strengths],
            "trials": trials,
            "comparisons_per_pair": comparisons_per_pair,
            "seed": int(seed),
            "prune_threshold": float(prune_threshold),
            "min_comparisons": min_comparisons,
        },
        "metrics": {
            "top_rank_recovery": _rate_with_standard_error(top_recovered, trials),
            "full_rank_recovery": _rate_with_standard_error(full_order_recovered, trials),
            "marginal_interval_coverage": _rate_with_standard_error(
                covered, coverage_total
            ),
            "false_prune": _rate_with_standard_error(false_pruned, false_prune_total),
            "true_prune_detection": _rate_with_standard_error(
                correctly_pruned, true_prune_total
            ),
        },
    }


__all__ = ["simulate_bt_diagnostics"]
