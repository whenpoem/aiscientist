"""Sequestered-dataset query tool.

Owns ``ver_heldout_queries`` writes; coordinates with ``ver_heldout_budgets``
which is owned by :mod:`verify_mcp.heldout`. Routes every model invocation
through the budget reservation + manifest verification path.
"""

from __future__ import annotations

from pathlib import Path

from claudescientist.heldout import compute_manifest, load_manifest
from claudescientist.runtime import extract_metric_tokens
from verify_mcp.db import tx

from ._common import _emit_event, _run_script


def _parse_metric_value(stdout: str) -> float | None:
    tokens = extract_metric_tokens(stdout)
    if not tokens:
        return None
    token = tokens[0].strip().rstrip("%")
    try:
        return float(token.replace(",", ""))
    except ValueError:
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
    """Run a model script against a registered sequestered dataset."""

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
