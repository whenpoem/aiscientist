"""Budget parsing helpers for verify_mcp."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

_BUDGET_PATTERNS: dict[str, re.Pattern[str]] = {
    "epochs": re.compile(
        r"\bepochs?\b[^0-9]{0,24}(?P<value>[\d,]+)",
        re.IGNORECASE,
    ),
    "lr_trials": re.compile(
        r"\blr[-_ ]?trials?\b[^0-9]{0,24}(?P<value>[\d,]+)",
        re.IGNORECASE,
    ),
    "param_count": re.compile(
        r"\b(?:#\s*)?(?:params?|parameters?|num[-_ ]?params?)\b[^0-9]{0,24}(?P<value>[\d,]+)",
        re.IGNORECASE,
    ),
}


@dataclass(slots=True)
class BudgetSnapshot:
    """Parsed budget axes from a run log."""

    epochs: int | None
    lr_trials: int | None
    param_count: int | None
    total_budget: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_int(value: str) -> int:
    return int(value.replace(",", ""))


def _extract_axis(text: str, pattern: re.Pattern[str]) -> int | None:
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    return _parse_int(match.group("value"))


def extract_budget(text: str) -> dict[str, Any]:
    """Extract coarse training-budget axes from a free-form log."""

    snapshot = BudgetSnapshot(
        epochs=_extract_axis(text, _BUDGET_PATTERNS["epochs"]),
        lr_trials=_extract_axis(text, _BUDGET_PATTERNS["lr_trials"]),
        param_count=_extract_axis(text, _BUDGET_PATTERNS["param_count"]),
        total_budget=None,
    )
    if (
        snapshot.epochs is not None
        and snapshot.lr_trials is not None
        and snapshot.param_count is not None
    ):
        snapshot.total_budget = snapshot.epochs * snapshot.lr_trials * snapshot.param_count
    return snapshot.to_dict()


def budget_ratios(proposed: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    """Compute axis-wise ratios between two budget snapshots."""

    ratios: dict[str, float] = {}
    for key in ("epochs", "lr_trials", "param_count", "total_budget"):
        proposed_value = proposed.get(key)
        baseline_value = baseline.get(key)
        if proposed_value is None or baseline_value in (None, 0):
            continue
        ratios[key] = float(proposed_value) / float(baseline_value)
    return ratios
