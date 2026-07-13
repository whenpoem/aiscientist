from __future__ import annotations

import pytest

from memory_mcp.bt_simulation import simulate_bt_diagnostics


def test_bt_simulation_is_deterministic_and_keeps_uncalibrated_contract():
    kwargs = {
        "true_strengths": (-1.0, 0.0, 1.0),
        "trials": 80,
        "comparisons_per_pair": 16,
        "seed": 42,
    }
    first = simulate_bt_diagnostics(**kwargs)
    second = simulate_bt_diagnostics(**kwargs)

    assert first == second
    assert first["contract"]["interval_calibrated"] is False
    assert first["contract"]["interval_level"] == 0.95
    assert first["metrics"]["top_rank_recovery"]["rate"] >= 0.9
    assert first["metrics"]["full_rank_recovery"]["rate"] >= 0.75
    assert 0.0 <= first["metrics"]["marginal_interval_coverage"]["rate"] <= 1.0
    assert 0.0 <= first["metrics"]["false_prune"]["rate"] <= 1.0


def test_bt_simulation_reports_candidate_denominators():
    result = simulate_bt_diagnostics(
        true_strengths=(-0.6, 0.1, 0.5),
        trials=12,
        comparisons_per_pair=4,
        seed=7,
        prune_threshold=0.0,
        min_comparisons=1,
    )

    coverage = result["metrics"]["marginal_interval_coverage"]
    false_prune = result["metrics"]["false_prune"]
    true_prune = result["metrics"]["true_prune_detection"]
    assert coverage["total"] == 36
    assert false_prune["total"] == 24
    assert true_prune["total"] == 12


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"true_strengths": (0.0, 1.0)}, "at least three"),
        ({"true_strengths": (0.0, 0.0, 1.0)}, "distinct"),
        ({"trials": 0}, "trials"),
        ({"comparisons_per_pair": 0}, "comparisons_per_pair"),
        ({"min_comparisons": 0}, "min_comparisons"),
    ],
)
def test_bt_simulation_validates_inputs(kwargs, message):
    with pytest.raises(ValueError, match=message):
        simulate_bt_diagnostics(**kwargs)
