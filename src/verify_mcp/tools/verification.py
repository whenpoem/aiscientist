"""Verification tools that exercise external scripts: seed perturbation, fairness."""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from claudescientist.runtime import extract_metric_tokens
from verify_mcp.budget import budget_ratios, extract_budget
from verify_mcp.db import _connect, tx

from ._common import _emit_event, _run_script


def _read_text(value: str) -> str:
    path = Path(value)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return value


def _extract_pattern_value(text: str, pattern: str) -> float | None:
    matches = list(re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE))
    if not matches:
        return None
    match = matches[-1]
    value = match.groupdict().get("value") if match.groupdict() else None
    if value is None:
        groups = [group for group in match.groups() if group is not None]
        value = groups[-1] if groups else match.group(0)
    try:
        return float(value.replace(",", "").rstrip("%"))
    except ValueError:
        return None


def _verify_metric_pin(metric_pin_id: int | None) -> dict[str, object] | None:
    if metric_pin_id is None:
        return None
    con = _connect()
    try:
        row = con.execute(
            "SELECT id, claim, value FROM ver_metric_pins WHERE id = ?",
            (metric_pin_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return {"ok": False, "error": "unknown_metric_pin", "metric_pin_id": metric_pin_id}
    return None


# ``extract_metric_tokens`` is imported but the verification tools below do
# not currently call it directly; downstream consumers (and historical
# callers via ``verify_mcp.impl``) sometimes import it through this module.
__all__ = [
    "extract_metric_tokens",
    "seed_perturb",
    "baseline_fairness",
]


def seed_perturb(
    script_path: str,
    seed_arg: str = "--seed",
    seeds: list[int] | None = None,
    metric_pattern: str = r"test[_ ]acc(?:uracy)?[: =]+([\d.]+)",
    timeout_sec: int = 600,
    stability_tol: float = 0.01,
    metric_pin_id: int | None = None,
    seed_env: str | None = "PYTHONHASHSEED",
    extra_env: dict[str, str] | None = None,
) -> dict:
    """Run a training script across multiple seeds and summarize the metric."""

    if seeds is None:
        seeds = [0, 1, 2]
    if not seeds:
        raise ValueError("seeds must not be empty.")

    metric_pin_error = _verify_metric_pin(metric_pin_id)
    if metric_pin_error is not None:
        return metric_pin_error

    values: list[float] = []
    outputs: list[str] = []
    for seed in seeds:
        env_overrides = dict(extra_env or {})
        if seed_env:
            env_overrides[seed_env] = str(seed)
        completed = _run_script(
            script_path,
            [seed_arg, str(seed)],
            timeout_sec=timeout_sec,
            env_overrides=env_overrides or None,
        )
        if completed.returncode != 0:
            return {
                "ok": False,
                "error": "script_failed",
                "seed": seed,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        metric_value = _extract_pattern_value(completed.stdout, metric_pattern)
        if metric_value is None:
            return {
                "ok": False,
                "error": "metric_parse_failed",
                "seed": seed,
                "stdout": completed.stdout,
            }
        values.append(metric_value)
        outputs.append(completed.stdout)

    mean_value = statistics.fmean(values)
    std_value = statistics.stdev(values) if len(values) > 1 else 0.0
    verdict = "stable" if std_value < stability_tol else "unstable"

    with tx() as con:
        cur = con.execute(
            """
            INSERT INTO ver_seed_runs(
              script_path, seed_arg, seeds_json, metric_pattern, values_json,
              mean_value, std_value, verdict, metric_pin_id
            )
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                str(script_path),
                seed_arg,
                json.dumps(seeds, ensure_ascii=True),
                metric_pattern,
                json.dumps(values, ensure_ascii=True),
                mean_value,
                std_value,
                verdict,
                metric_pin_id,
            ),
        )
        run_id = int(cur.lastrowid)
        _emit_event(
            con,
            "seed_run_recorded",
            {
                "run_id": run_id,
                "script_path": str(script_path),
                "metric_pin_id": metric_pin_id,
                "verdict": verdict,
                "mean_value": mean_value,
                "std_value": std_value,
            },
        )

    return {
        "ok": True,
        "run_id": run_id,
        "script_path": str(script_path),
        "seed_arg": seed_arg,
        "seed_env": seed_env,
        "seeds": seeds,
        "values": values,
        "mean_value": mean_value,
        "std_value": std_value,
        "verdict": verdict,
        "metric_pin_id": metric_pin_id,
        "stdout": outputs,
    }


def baseline_fairness(
    proposed_log: str,
    baseline_log: str,
    threshold_ratio: float = 3.0,
) -> dict:
    """Compare training budget between a proposed method and a baseline."""

    proposed_text = _read_text(proposed_log)
    baseline_text = _read_text(baseline_log)
    proposed = extract_budget(proposed_text)
    baseline = extract_budget(baseline_text)
    if any(proposed.get(key) is None for key in ("epochs", "lr_trials", "param_count")):
        return {"ok": False, "error": "budget_parse_failed", "which": "proposed"}
    if any(baseline.get(key) is None for key in ("epochs", "lr_trials", "param_count")):
        return {"ok": False, "error": "budget_parse_failed", "which": "baseline"}

    ratios = budget_ratios(proposed, baseline)
    unfair_axes = {axis: ratio for axis, ratio in ratios.items() if ratio > threshold_ratio}
    verdict = "fair" if not unfair_axes else "unfair"
    return {
        "ok": True,
        "verdict": verdict,
        "threshold_ratio": threshold_ratio,
        "proposed": proposed,
        "baseline": baseline,
        "ratios": ratios,
        "unfair_axes": unfair_axes,
        "total_ratio": ratios.get("total_budget"),
    }
