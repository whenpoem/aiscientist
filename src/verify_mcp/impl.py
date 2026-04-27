"""Tool implementations for verify_mcp."""

from __future__ import annotations

import hashlib
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
    "refresh_claim",
    "preregister",
    "resolve_preregistration",
    "list_preregistrations",
    "budget_check",
    "budget_consume",
]

VALID_DIRECTIONS = {"higher_better", "lower_better"}
VALID_MC_CORRECTIONS = {"bh", "bonferroni", "none"}
VALID_BUDGET_RESOURCES = {
    "wallclock_sec",
    "llm_tokens",
    "heldout_queries",
    "disk_mb",
}


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


def _hash_file(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _compute_input_hashes(input_files: list[str] | None) -> list[dict[str, str | None]]:
    if not input_files:
        return []
    hashes: list[dict[str, str | None]] = []
    for raw in input_files:
        path = Path(str(raw)).expanduser()
        hashes.append({"path": str(path), "sha256": _hash_file(path)})
    return hashes


def _record_provenance_dag(
    con,
    *,
    prov_id: int,
    input_files: list[str] | None,
    parent_prov_ids: list[int] | None,
) -> dict:
    input_hashes = _compute_input_hashes(input_files)
    output_seed = "|".join(
        f"{entry.get('path','')}::{entry.get('sha256') or ''}" for entry in input_hashes
    )
    output_hash = (
        hashlib.sha256(output_seed.encode("utf-8")).hexdigest() if input_hashes else ""
    )
    con.execute(
        """
        INSERT INTO ver_provenance_dag(
          prov_id, input_hashes, output_hash, parent_prov_ids, stale, refreshed_at
        )
        VALUES(?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(prov_id) DO UPDATE SET
          input_hashes = excluded.input_hashes,
          output_hash = excluded.output_hash,
          parent_prov_ids = excluded.parent_prov_ids,
          stale = 0,
          refreshed_at = CURRENT_TIMESTAMP
        """,
        (
            int(prov_id),
            json.dumps(input_hashes, ensure_ascii=True),
            output_hash,
            json.dumps([int(pid) for pid in (parent_prov_ids or [])], ensure_ascii=True),
        ),
    )
    return {
        "prov_id": int(prov_id),
        "input_hashes": input_hashes,
        "output_hash": output_hash,
    }


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


def record_provenance(
    claim: str,
    value: str,
    session_id: str,
    source_command: str = "",
    input_files: list[str] | None = None,
    parent_prov_ids: list[int] | None = None,
) -> dict:
    """Store provenance for a numeric claim.

    When ``input_files`` is provided each path is hashed (sha256) and the
    resulting fingerprint is stored in ``ver_provenance_dag`` so the chain
    can later be re-validated by :func:`refresh_claim`.
    """
    provenance_id = _insert_provenance(
        claim=claim,
        value=str(value),
        session_id=session_id,
        source_command=source_command,
    )
    if input_files or parent_prov_ids:
        with tx() as con:
            dag = _record_provenance_dag(
                con,
                prov_id=provenance_id,
                input_files=input_files,
                parent_prov_ids=parent_prov_ids,
            )
        return {"recorded": True, "provenance_id": provenance_id, "dag": dag}
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


def _empty_seed_summary() -> dict:
    return {
        "seed_verdict": "missing",
        "seed_run_count": 0,
        "stable_seed_runs": 0,
        "latest_seed_run_id": None,
        "seed_runs": [],
    }


def _seed_summaries_for_pins(con, pin_ids: list[int]) -> dict[int, dict]:
    if not pin_ids:
        return {}
    placeholders = ",".join("?" for _ in pin_ids)
    rows = con.execute(
        f"""
        SELECT run_id, metric_pin_id, seeds_json, values_json, mean_value,
               std_value, verdict, created_at
        FROM ver_seed_runs
        WHERE metric_pin_id IN ({placeholders})
        ORDER BY created_at DESC, run_id DESC
        """,
        tuple(pin_ids),
    ).fetchall()
    summaries = {pin_id: _empty_seed_summary() for pin_id in pin_ids}
    for row in rows:
        pin_id = int(row["metric_pin_id"])
        summary = summaries.setdefault(pin_id, _empty_seed_summary())
        run = {
            "run_id": int(row["run_id"]),
            "verdict": row["verdict"],
            "mean_value": float(row["mean_value"]),
            "std_value": float(row["std_value"]),
            "created_at": row["created_at"],
        }
        summary["seed_run_count"] += 1
        if row["verdict"] == "stable":
            summary["stable_seed_runs"] += 1
        if summary["latest_seed_run_id"] is None:
            summary["latest_seed_run_id"] = int(row["run_id"])
            summary["seed_verdict"] = row["verdict"]
        if len(summary["seed_runs"]) < 5:
            summary["seed_runs"].append(run)
    return summaries


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
        pin_dicts = [dict(pin) for pin in pins]
        seed_summaries = _seed_summaries_for_pins(
            con,
            [int(pin["id"]) for pin in pin_dicts],
        )
        for pin in pin_dicts:
            pin["pin_id"] = int(pin["id"])
            pin.update(seed_summaries.get(int(pin["id"]), _empty_seed_summary()))
        return {
            "status": "found",
            "evidence": [dict(row) for row in rows],
            "pins": pin_dicts,
        }
    finally:
        con.close()


def refresh_claim(claim: str) -> dict:
    """Walk ``ver_provenance_dag`` for a claim and re-hash recorded inputs.

    Returns the chain of provenance rows attached to the claim with each
    row's stale flag re-evaluated. Stale rows emit ``prov_dag_stale`` events.
    """
    normalized_claim = normalize_claim(claim)
    affected: list[dict] = []
    with tx() as con:
        rows = con.execute(
            """
            SELECT p.id AS prov_id, p.claim, p.value, p.session_id, p.source_command,
                   d.input_hashes, d.output_hash, d.parent_prov_ids, d.stale,
                   d.refreshed_at
            FROM ver_provenance p
            LEFT JOIN ver_provenance_dag d ON d.prov_id = p.id
            WHERE p.claim = ?
            ORDER BY p.created_at DESC, p.id DESC
            """,
            (normalized_claim,),
        ).fetchall()
        if not rows:
            return {"status": "missing", "claim": normalized_claim, "checked": []}

        for row in rows:
            prov_id = int(row["prov_id"])
            stored_raw = row["input_hashes"]
            if stored_raw is None:
                affected.append(
                    {
                        "prov_id": prov_id,
                        "stale": False,
                        "reason": "no_dag_entry",
                    }
                )
                continue
            try:
                stored = json.loads(stored_raw)
            except (TypeError, json.JSONDecodeError):
                stored = []

            mismatched: list[dict[str, str | None]] = []
            for entry in stored:
                path = Path(str(entry.get("path", "")))
                expected = entry.get("sha256")
                actual = _hash_file(path) if str(path) else None
                if expected != actual:
                    mismatched.append(
                        {
                            "path": str(path),
                            "expected": expected,
                            "actual": actual,
                        }
                    )

            stale = 1 if mismatched else 0
            con.execute(
                """
                UPDATE ver_provenance_dag
                SET stale = ?, refreshed_at = CURRENT_TIMESTAMP
                WHERE prov_id = ?
                """,
                (stale, prov_id),
            )
            if stale:
                _emit_event(
                    con,
                    "prov_dag_stale",
                    {
                        "prov_id": prov_id,
                        "claim": normalized_claim,
                        "mismatched": mismatched,
                    },
                )
            affected.append(
                {
                    "prov_id": prov_id,
                    "stale": bool(stale),
                    "mismatched": mismatched,
                    "input_count": len(stored),
                }
            )

    stale_count = sum(1 for entry in affected if entry.get("stale"))
    return {
        "status": "stale" if stale_count else "fresh",
        "claim": normalized_claim,
        "checked": affected,
        "stale_count": stale_count,
    }


def _new_prereg_id() -> str:
    from uuid import uuid4

    return f"prereg_{uuid4().hex[:12]}"


def _bh_threshold(open_count: int, alpha: float) -> float:
    """Benjamini-Hochberg adjusted alpha for the most significant rank."""
    rank = max(1, int(open_count))
    return float(alpha) / rank


def _adjust_p_value(
    observed_p_value: float | None,
    mc_correction: str,
    open_count: int,
) -> float | None:
    if observed_p_value is None:
        return None
    raw_p = float(observed_p_value)
    if not (0.0 <= raw_p <= 1.0):
        raise ValueError("observed_p_value must be in [0, 1]")
    if mc_correction == "none":
        return raw_p
    return min(1.0, raw_p * max(1, int(open_count)))


def preregister(
    hypothesis_id: str | None,
    metric_name: str,
    direction: str,
    threshold: float | None,
    heldout_dataset: str | None = None,
    seed_count: int = 5,
    alpha: float = 0.05,
    mc_correction: str = "bh",
) -> dict:
    """Lock a falsification target for a hypothesis before running experiments."""
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(VALID_DIRECTIONS)}")
    if mc_correction not in VALID_MC_CORRECTIONS:
        raise ValueError(
            f"mc_correction must be one of {sorted(VALID_MC_CORRECTIONS)}"
        )
    if seed_count <= 0:
        raise ValueError("seed_count must be positive")
    if not (0.0 < float(alpha) < 1.0):
        raise ValueError("alpha must be in (0, 1)")

    prereg_id = _new_prereg_id()
    with tx() as con:
        con.execute(
            """
            INSERT INTO ver_preregistrations(
              prereg_id, hypothesis_id, metric_name, direction, threshold,
              heldout_dataset, seed_count, alpha, mc_correction
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                prereg_id,
                hypothesis_id,
                normalize_claim(metric_name),
                direction,
                None if threshold is None else float(threshold),
                heldout_dataset,
                int(seed_count),
                float(alpha),
                mc_correction,
            ),
        )
        _emit_event(
            con,
            "prereg_locked",
            {
                "prereg_id": prereg_id,
                "hypothesis_id": hypothesis_id,
                "metric_name": metric_name,
                "direction": direction,
                "threshold": threshold,
                "alpha": alpha,
                "mc_correction": mc_correction,
            },
        )
    return {
        "prereg_id": prereg_id,
        "hypothesis_id": hypothesis_id,
        "metric_name": normalize_claim(metric_name),
        "direction": direction,
        "threshold": threshold,
        "status": "open",
    }


def _direction_meets_threshold(direction: str, observed: float, threshold: float) -> bool:
    if direction == "higher_better":
        return observed >= threshold
    return observed <= threshold


def resolve_preregistration(
    prereg_id: str,
    observed_value: float,
    observed_p_value: float | None = None,
) -> dict:
    """Compare a locked prereg against observed evidence and freeze its verdict.

    The Benjamini-Hochberg / Bonferroni correction operates on the count of
    *currently open* prereg rows so each new resolve sees a stricter alpha
    until the open queue drains. ``observed_p_value`` is optional; when it is
    not supplied the verdict only uses the threshold.
    """
    with tx() as con:
        row = con.execute(
            """
            SELECT prereg_id, hypothesis_id, metric_name, direction, threshold,
                   alpha, mc_correction, status
            FROM ver_preregistrations
            WHERE prereg_id = ?
            """,
            (prereg_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "unknown_prereg", "prereg_id": prereg_id}
        if row["status"] != "open":
            return {
                "ok": False,
                "error": "already_resolved",
                "prereg_id": prereg_id,
                "status": row["status"],
            }

        open_count = int(
            con.execute(
                "SELECT COUNT(*) FROM ver_preregistrations WHERE status = 'open'"
            ).fetchone()[0]
        )
        threshold = row["threshold"]
        alpha = float(row["alpha"])
        mc_correction = row["mc_correction"]

        if mc_correction == "bonferroni":
            adjusted_alpha = alpha / max(1, open_count)
        elif mc_correction == "bh":
            adjusted_alpha = _bh_threshold(open_count, alpha)
        else:
            adjusted_alpha = alpha

        meets_threshold = (
            threshold is None
            or _direction_meets_threshold(
                row["direction"], float(observed_value), float(threshold)
            )
        )
        adjusted_p_value = _adjust_p_value(
            observed_p_value,
            mc_correction,
            open_count,
        )
        meets_significance = adjusted_p_value is None or adjusted_p_value <= alpha
        new_status = "met" if (meets_threshold and meets_significance) else "missed"

        con.execute(
            """
            UPDATE ver_preregistrations
            SET observed_value = ?, observed_p_value = ?,
                adjusted_p_value = ?, status = ?,
                resolved_at = CURRENT_TIMESTAMP
            WHERE prereg_id = ?
            """,
            (
                float(observed_value),
                float(observed_p_value) if observed_p_value is not None else None,
                adjusted_p_value,
                new_status,
                prereg_id,
            ),
        )
        _emit_event(
            con,
            "prereg_resolved",
            {
                "prereg_id": prereg_id,
                "hypothesis_id": row["hypothesis_id"],
                "metric_name": row["metric_name"],
                "status": new_status,
                "observed_value": observed_value,
                "adjusted_alpha": adjusted_alpha,
                "adjusted_p_value": adjusted_p_value,
            },
        )
    return {
        "ok": True,
        "prereg_id": prereg_id,
        "hypothesis_id": row["hypothesis_id"],
        "metric_name": row["metric_name"],
        "status": new_status,
        "observed_value": float(observed_value),
        "observed_p_value": float(observed_p_value) if observed_p_value is not None else None,
        "adjusted_p_value": adjusted_p_value,
        "adjusted_alpha": adjusted_alpha,
        "mc_correction": mc_correction,
    }


def list_preregistrations(
    status: str | None = None,
    hypothesis_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Read-only list of preregistrations, latest first."""
    if status is not None and status not in {"open", "met", "missed", "withdrawn"}:
        raise ValueError("status must be one of: open, met, missed, withdrawn")
    clauses: list[str] = []
    params: list[object] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if hypothesis_id is not None:
        clauses.append("hypothesis_id = ?")
        params.append(hypothesis_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, int(limit)))

    con = _connect()
    try:
        rows = con.execute(
            f"""
            SELECT prereg_id, hypothesis_id, metric_name, direction, threshold,
                   heldout_dataset, seed_count, alpha, mc_correction,
                   observed_value, observed_p_value, adjusted_p_value,
                   resolution_note, locked_at, resolved_at, status
            FROM ver_preregistrations
            {where}
            ORDER BY locked_at DESC, prereg_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    finally:
        con.close()
    return [dict(row) for row in rows]


def budget_check(
    scope: str,
    resource: str,
    requested: float,
    window: str = "session",
) -> dict:
    """Return whether ``requested`` units fit within the configured window."""
    if resource not in VALID_BUDGET_RESOURCES:
        raise ValueError(f"resource must be one of {sorted(VALID_BUDGET_RESOURCES)}")
    if requested < 0:
        raise ValueError("requested must be non-negative")

    con = _connect()
    try:
        row = con.execute(
            """
            SELECT limit_value, used_value, window
            FROM res_budget_ledger
            WHERE scope = ? AND resource = ? AND window = ?
            LIMIT 1
            """,
            (scope, resource, window),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return {
            "allowed": True,
            "scope": scope,
            "resource": resource,
            "window": window,
            "limit": None,
            "used": 0.0,
            "remaining": None,
            "requested": float(requested),
            "action_if_denied": None,
            "reason": "no_budget_configured",
        }
    remaining = float(row["limit_value"]) - float(row["used_value"])
    allowed = float(requested) <= remaining + 1e-9
    return {
        "allowed": bool(allowed),
        "scope": scope,
        "resource": resource,
        "window": row["window"],
        "limit": float(row["limit_value"]),
        "used": float(row["used_value"]),
        "remaining": remaining,
        "requested": float(requested),
        "action_if_denied": "halt" if not allowed else None,
    }


def budget_consume(
    scope: str,
    resource: str,
    amount: float,
    note: str = "",
    limit_value: float | None = None,
    window: str = "session",
) -> dict:
    """Atomically reserve ``amount`` units from the budget ledger.

    When the (scope, resource, window) row does not yet exist callers must
    pass ``limit_value`` so we can create it. Subsequent calls only need
    ``amount``. Going over the configured limit emits ``budget_exceeded``.
    """
    if resource not in VALID_BUDGET_RESOURCES:
        raise ValueError(f"resource must be one of {sorted(VALID_BUDGET_RESOURCES)}")
    if amount < 0:
        raise ValueError("amount must be non-negative")

    with tx() as con:
        row = con.execute(
            """
            SELECT budget_id, limit_value, used_value
            FROM res_budget_ledger
            WHERE scope = ? AND resource = ? AND window = ?
            """,
            (scope, resource, window),
        ).fetchone()
        if row is None:
            if limit_value is None:
                raise ValueError(
                    "budget_consume requires limit_value when the budget "
                    "row does not yet exist"
                )
            con.execute(
                """
                INSERT INTO res_budget_ledger(
                  scope, resource, limit_value, used_value, window, note
                ) VALUES(?,?,?,?,?,?)
                """,
                (scope, resource, float(limit_value), 0.0, window, note),
            )
            row = con.execute(
                """
                SELECT budget_id, limit_value, used_value
                FROM res_budget_ledger
                WHERE scope = ? AND resource = ? AND window = ?
                """,
                (scope, resource, window),
            ).fetchone()

        limit_v = float(row["limit_value"])
        used = float(row["used_value"])
        new_used = used + float(amount)
        if new_used > limit_v + 1e-9:
            _emit_event(
                con,
                "budget_exceeded",
                {
                    "scope": scope,
                    "resource": resource,
                    "window": window,
                    "limit": limit_v,
                    "used": used,
                    "requested": float(amount),
                },
            )
            return {
                "ok": False,
                "error": "budget_exceeded",
                "scope": scope,
                "resource": resource,
                "window": window,
                "limit": limit_v,
                "used": used,
                "remaining": max(0.0, limit_v - used),
            }
        con.execute(
            """
            UPDATE res_budget_ledger
            SET used_value = ?, updated_at = CURRENT_TIMESTAMP,
                note = CASE WHEN ? = '' THEN note ELSE ? END
            WHERE budget_id = ?
            """,
            (new_used, note, note, int(row["budget_id"])),
        )
    return {
        "ok": True,
        "scope": scope,
        "resource": resource,
        "window": window,
        "limit": limit_v,
        "used": new_used,
        "remaining": max(0.0, limit_v - new_used),
        "consumed": float(amount),
    }


bootstrap()
