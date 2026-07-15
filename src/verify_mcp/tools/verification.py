"""Verification tools that exercise external scripts: seed perturbation, fairness."""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

from claudescientist.runtime import extract_metric_tokens
from verify_mcp.budget import budget_ratios, extract_budget
from verify_mcp.db import _connect, tx
from verify_mcp.run_manifest import capture_run_manifest, store_run_manifest

from ._common import _emit_event, _run_script


def _read_text(value: str) -> str:
    path = Path(value)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return value


def _extract_pattern_value(text: str, pattern: str) -> float | None:
    matches = list(re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE))
    if matches:
        match = matches[-1]
        value = match.groupdict().get("value") if match.groupdict() else None
        if value is None:
            groups = [group for group in match.groups() if group is not None]
            value = groups[-1] if groups else match.group(0)
    else:
        tokens = extract_metric_tokens(text)
        value = tokens[-1] if tokens else None
    if value is None:
        return None
    try:
        return float(value.replace(",", "").rstrip("%"))
    except ValueError:
        return None


def _resolve_metric_pin(
    metric_pin_id: int | None,
) -> tuple[int | None, dict[str, object] | None]:
    if metric_pin_id is None:
        return None, None
    con = _connect()
    try:
        row = con.execute(
            "SELECT id, provenance_id FROM ver_metric_pins WHERE id = ?",
            (metric_pin_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None, {
            "ok": False,
            "error": "unknown_metric_pin",
            "metric_pin_id": metric_pin_id,
        }
    return int(row["provenance_id"]), None


def _stability_threshold(
    mean_value: float,
    stability_tol: float,
    stability_mode: str,
) -> tuple[float, str]:
    if stability_tol < 0:
        raise ValueError("stability_tol must be non-negative.")
    if stability_mode not in {"absolute", "relative", "auto"}:
        raise ValueError("stability_mode must be one of: absolute, relative, auto")
    if stability_mode == "absolute":
        return float(stability_tol), "absolute"
    relative_threshold = abs(float(mean_value)) * float(stability_tol)
    if stability_mode == "relative":
        return relative_threshold, "relative"
    return max(float(stability_tol), relative_threshold), "auto"


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
    stability_mode: str = "auto",
    metric_pin_id: int | None = None,
    seed_env: str | None = "PYTHONHASHSEED",
    extra_env: dict[str, str] | None = None,
    input_files: list[str] | None = None,
    config_files: list[str] | None = None,
) -> dict:
    """Run a training script across multiple seeds and summarize the metric."""

    if seeds is None:
        seeds = [0, 1, 2]
    if not seeds:
        raise ValueError("seeds must not be empty.")

    provenance_id, metric_pin_error = _resolve_metric_pin(metric_pin_id)
    if metric_pin_error is not None:
        return metric_pin_error

    command = f"{sys.executable} {script_path} {seed_arg} <seed>"
    manifest = capture_run_manifest(
        command=command,
        script_path=script_path,
        input_files=input_files,
        config_files=config_files,
        seeds=seeds,
        env_overrides=extra_env,
    )

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
    threshold, resolved_stability_mode = _stability_threshold(
        mean_value,
        stability_tol,
        stability_mode,
    )
    verdict = "stable" if std_value <= threshold else "unstable"
    relative_std = std_value / abs(mean_value) if mean_value else None

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
        stored_manifest = store_run_manifest(
            con,
            manifest,
            provenance_id=provenance_id,
            seed_run_id=run_id,
        )
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
                "stability_threshold": threshold,
                "stability_mode": resolved_stability_mode,
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
        "relative_std": relative_std,
        "stability_tol": stability_tol,
        "stability_threshold": threshold,
        "stability_mode": resolved_stability_mode,
        "verdict": verdict,
        "metric_pin_id": metric_pin_id,
        "run_manifest": stored_manifest,
        "stdout": outputs,
    }


def baseline_fairness(
    proposed_log: str,
    baseline_log: str,
    threshold_ratio: float = 3.0,
) -> dict:
    """Run the compatibility-named advisory budget-parity check.

    This compares only the budget fields recoverable from the two logs. It is
    not evidence that the methods are fair in every scientific sense.
    """

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
        "check": "budget_parity",
        "protection_level": "advisory",
        "verdict": verdict,
        "threshold_ratio": threshold_ratio,
        "proposed": proposed,
        "baseline": baseline,
        "ratios": ratios,
        "unfair_axes": unfair_axes,
        "total_ratio": ratios.get("total_budget"),
        "interpretation": (
            "Budget parity check only; this is not a complete fairness proof."
        ),
    }
