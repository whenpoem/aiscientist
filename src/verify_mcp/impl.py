"""Tool implementations for verify_mcp."""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

from claudescientist.heldout import compute_manifest, load_manifest
from claudescientist.runtime import emit_cockpit_event

from .budget import budget_ratios, extract_budget
from .db import _connect, bootstrap, tx
from .leakage import scan_file, scan_python
from .provenance import extract_metric_tokens, normalize_claim, normalize_value

TOOL_NAMES = [
    "leakage_check",
    "record_provenance",
    "check_provenance",
    "pin_metric",
    "seed_perturb",
    "baseline_fairness",
    "query_heldout",
]


def _read_text(value: str) -> str:
    path = Path(value)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return value


def _run_script(
    script_path: str,
    args: list[str],
    *,
    timeout_sec: int,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = Path(script_path)
    if not script.exists():
        raise FileNotFoundError(script)
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env=env,
    )


def _parse_metric_value(stdout: str) -> float | None:
    tokens = extract_metric_tokens(stdout)
    if not tokens:
        return None
    token = tokens[0].strip().rstrip("%")
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def _emit_event(con, kind: str, payload: dict) -> None:
    emit_cockpit_event(con, kind, payload)


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


def _load_heldout_budget(
    con,
    dataset: str,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    row = con.execute(
        """
        SELECT dataset, heldout_path, manifest_sha256, budget_total, budget_used
        FROM ver_heldout_budgets
        WHERE dataset = ?
        """,
        (dataset,),
    ).fetchone()
    if row is None:
        return None, {"ok": False, "error": "unknown_dataset", "dataset": dataset}

    heldout_path = Path(row["heldout_path"])
    manifest_recorded = str(row["manifest_sha256"])
    manifest_file = load_manifest(heldout_path)
    if manifest_file is None or manifest_file.get("manifest_sha256") != manifest_recorded:
        return None, {"ok": False, "error": "manifest_drift", "dataset": dataset}
    current_manifest = compute_manifest(heldout_path)
    if current_manifest["manifest_sha256"] != manifest_recorded:
        return None, {"ok": False, "error": "manifest_drift", "dataset": dataset}

    return (
        {
            "dataset": str(row["dataset"]),
            "heldout_path": heldout_path,
            "manifest_sha256": manifest_recorded,
            "budget_total": int(row["budget_total"]),
            "budget_used": int(row["budget_used"]),
        },
        None,
    )


def _insert_provenance(
    *,
    claim: str,
    value: str,
    session_id: str,
    source_command: str,
) -> int:
    with tx() as con:
        cur = con.execute(
            """
            INSERT INTO ver_provenance(claim, value, session_id, source_command)
            VALUES(?,?,?,?)
            """,
            (normalize_claim(claim), normalize_value(value), session_id, source_command),
        )
        return int(cur.lastrowid)


def leakage_check(script_path: str | None = None, script_text: str | None = None) -> dict:
    """Run the leakage detector against a file path or raw script text."""
    if bool(script_path) == bool(script_text):
        raise ValueError("Provide exactly one of script_path or script_text.")
    findings = scan_file(script_path) if script_path else scan_python(script_text or "")
    return {"clean": len(findings) == 0, "findings": [finding.to_dict() for finding in findings]}


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


def _reserve_heldout_budget(
    *,
    dataset: str,
    model_path: str,
    batch_size: int,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    with tx() as con:
        validated, error = _load_heldout_budget(con, dataset)
        if error is not None:
            return None, error
        assert validated is not None
        budget_total = int(validated["budget_total"])
        budget_used = int(validated["budget_used"])
        if budget_used + batch_size > budget_total:
            return None, {
                "ok": False,
                "error": "budget_exceeded",
                "dataset": dataset,
                "budget_total": budget_total,
                "budget_used": budget_used,
            }

        cur = con.execute(
            """
            INSERT INTO ver_heldout_queries(dataset, model_path, batch_size, status)
            VALUES(?,?,?,?)
            """,
            (dataset, str(model_path), batch_size, "running"),
        )
        con.execute(
            """
            UPDATE ver_heldout_budgets
            SET budget_used = budget_used + ?
            WHERE dataset = ?
            """,
            (batch_size, dataset),
        )
        query_id = int(cur.lastrowid)
        reserved_used = budget_used + batch_size
        _emit_event(
            con,
            "heldout_query_reserved",
            {
                "query_id": query_id,
                "dataset": dataset,
                "batch_size": batch_size,
                "budget_used": reserved_used,
                "budget_total": budget_total,
            },
        )
        return (
            {
                **validated,
                "query_id": query_id,
                "budget_used": reserved_used,
                "remaining_budget": budget_total - reserved_used,
            },
            None,
        )


def _finish_heldout_query(
    *,
    query_id: int,
    status: str,
    metric_value: float | None = None,
    error: str = "",
) -> None:
    with tx() as con:
        con.execute(
            """
            UPDATE ver_heldout_queries
            SET status = ?, metric_value = ?, error = ?, completed_at = CURRENT_TIMESTAMP
            WHERE query_id = ?
            """,
            (status, metric_value, error[:500], query_id),
        )
        _emit_event(
            con,
            "heldout_query_finished",
            {
                "query_id": query_id,
                "status": status,
                "metric_value": metric_value,
                "error": error[:120],
            },
        )


def query_heldout(
    dataset: str,
    model_path: str,
    batch_size: int = 1,
    timeout_sec: int = 600,
) -> dict:
    """Run a model script against a registered held-out dataset."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")

    validated, error = _reserve_heldout_budget(
        dataset=dataset,
        model_path=model_path,
        batch_size=batch_size,
    )
    if error is not None:
        return error

    assert validated is not None
    heldout_path = validated["heldout_path"]
    budget_used = int(validated["budget_used"])
    budget_total = int(validated["budget_total"])
    remaining_budget = int(validated["remaining_budget"])
    query_id = int(validated["query_id"])

    completed = _run_script(
        model_path,
        ["--dataset", str(heldout_path), "--batch-size", str(batch_size)],
        timeout_sec=timeout_sec,
    )
    if completed.returncode != 0:
        _finish_heldout_query(
            query_id=query_id,
            status="failed",
            error=f"script_failed:{completed.returncode}",
        )
        return {
            "ok": False,
            "query_id": query_id,
            "error": "script_failed",
            "dataset": dataset,
            "returncode": completed.returncode,
            "budget_total": budget_total,
            "budget_used": budget_used,
            "remaining_budget": remaining_budget,
        }

    metric_value = _parse_metric_value(completed.stdout)
    if metric_value is None:
        _finish_heldout_query(
            query_id=query_id,
            status="failed",
            error="metric_parse_failed",
        )
        return {
            "ok": False,
            "query_id": query_id,
            "error": "metric_parse_failed",
            "dataset": dataset,
            "budget_total": budget_total,
            "budget_used": budget_used,
            "remaining_budget": remaining_budget,
        }

    _finish_heldout_query(query_id=query_id, status="completed", metric_value=metric_value)

    return {
        "ok": True,
        "query_id": query_id,
        "dataset": dataset,
        "model_path": str(model_path),
        "batch_size": batch_size,
        "metric_value": metric_value,
        "budget_total": budget_total,
        "budget_used": budget_used,
        "remaining_budget": remaining_budget,
    }


def record_provenance(claim: str, value: str, session_id: str, source_command: str = "") -> dict:
    """Store provenance for a numeric claim."""
    provenance_id = _insert_provenance(
        claim=claim,
        value=str(value),
        session_id=session_id,
        source_command=source_command,
    )
    return {"recorded": True, "provenance_id": provenance_id}


def pin_metric(
    claim: str,
    value: str,
    session_id: str,
    source_command: str = "",
    note: str = "",
) -> dict:
    """Pin a central metric to a provenance record for later write-up checks."""
    normalized_claim = normalize_claim(claim)
    normalized_value = normalize_value(value)
    with tx() as con:
        cur = con.execute(
            """
            INSERT INTO ver_provenance(claim, value, session_id, source_command)
            VALUES(?,?,?,?)
            """,
            (normalized_claim, normalized_value, session_id, source_command),
        )
        provenance_id = int(cur.lastrowid)
        pin = con.execute(
            """
            INSERT INTO ver_metric_pins(
                claim, value, provenance_id, session_id, source_command, note
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                normalized_claim,
                normalized_value,
                provenance_id,
                session_id,
                source_command,
                note.strip(),
            ),
        )
        pin_id = int(pin.lastrowid)
        _emit_event(
            con,
            "claim_pinned",
            {
                "pin_id": pin_id,
                "claim": normalized_claim,
                "value": normalized_value,
                "session_id": session_id,
            },
        )
    return {"pinned": True, "pin_id": pin_id, "provenance_id": provenance_id}


def check_provenance(claim: str) -> dict:
    """Return the latest provenance evidence for a claim."""
    normalized_claim = normalize_claim(claim)
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT id, claim, value, session_id, source_command, created_at
            FROM ver_provenance
            WHERE claim = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 20
            """,
            (normalized_claim,),
        ).fetchall()
        pins = con.execute(
            """
            SELECT id, claim, value, provenance_id, session_id, source_command, note, created_at
            FROM ver_metric_pins
            WHERE claim = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 20
            """,
            (normalized_claim,),
        ).fetchall()
        if not rows:
            return {"status": "missing"}
        return {
            "status": "found",
            "evidence": [dict(row) for row in rows],
            "pins": [dict(pin) for pin in pins],
        }
    finally:
        con.close()


bootstrap()
