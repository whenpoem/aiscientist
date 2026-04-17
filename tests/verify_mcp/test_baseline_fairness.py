from __future__ import annotations

from pathlib import Path

import pytest


def test_baseline_fairness_accepts_equal_budgets(workspace):
    impl = workspace["verify_mcp.impl"]
    fixture = Path(__file__).with_name("fixtures") / "budget_equal.log"

    result = impl.baseline_fairness(str(fixture), str(fixture))

    assert result["ok"] is True
    assert result["verdict"] == "fair"
    assert result["proposed"]["epochs"] == 10
    assert result["proposed"]["lr_trials"] == 2
    assert result["proposed"]["param_count"] == 100000
    assert result["proposed"]["total_budget"] == 2_000_000
    assert result["ratios"]["total_budget"] == pytest.approx(1.0)
    assert result["unfair_axes"] == {}


def test_baseline_fairness_flags_budget_blowup(workspace):
    impl = workspace["verify_mcp.impl"]
    proposed = Path(__file__).with_name("fixtures") / "budget_inflated.log"
    baseline = Path(__file__).with_name("fixtures") / "budget_equal.log"

    result = impl.baseline_fairness(str(proposed), str(baseline), threshold_ratio=3.0)

    assert result["ok"] is True
    assert result["verdict"] == "unfair"
    assert result["ratios"]["epochs"] == pytest.approx(3.0)
    assert result["ratios"]["lr_trials"] == pytest.approx(4.0)
    assert result["ratios"]["param_count"] == pytest.approx(4.0)
    assert result["ratios"]["total_budget"] == pytest.approx(48.0)
    assert "total_budget" in result["unfair_axes"]
