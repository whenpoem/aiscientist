"""Preregistration tools and multiple-comparison correction logic."""

from __future__ import annotations

from uuid import uuid4

from verify_mcp.db import _connect, tx
from verify_mcp.provenance import normalize_claim

from ._common import _emit_event

VALID_DIRECTIONS = {"higher_better", "lower_better"}
VALID_MC_CORRECTIONS = {"bh", "bonferroni", "none"}


def _new_prereg_id() -> str:
    return f"prereg_{uuid4().hex[:12]}"


def _canonical_mc_correction(mc_correction: str) -> str:
    """Store new prereg rows with the current correction name."""
    if mc_correction == "bh":
        return "bonferroni"
    return mc_correction


def _bonferroni_threshold(family_size: int, alpha: float) -> float:
    """Return the fixed-family Bonferroni alpha threshold."""
    return float(alpha) / max(1, int(family_size))


def _adjust_p_value(
    observed_p_value: float | None,
    mc_correction: str,
    family_size: int,
) -> float | None:
    if observed_p_value is None:
        return None
    raw_p = float(observed_p_value)
    if not (0.0 <= raw_p <= 1.0):
        raise ValueError("observed_p_value must be in [0, 1]")
    if mc_correction == "none":
        return raw_p
    return min(1.0, raw_p * max(1, int(family_size)))


def _direction_meets_threshold(direction: str, observed: float, threshold: float) -> bool:
    if direction == "higher_better":
        return observed >= threshold
    return observed <= threshold


def preregister(
    hypothesis_id: str | None,
    metric_name: str,
    direction: str,
    threshold: float | None,
    heldout_dataset: str | None = None,
    seed_count: int = 5,
    alpha: float = 0.05,
    mc_correction: str = "bonferroni",
    family_id: str | None = None,
    family_size: int = 1,
) -> dict:
    """Lock a falsification target for a hypothesis before running experiments."""
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(VALID_DIRECTIONS)}")
    if mc_correction not in VALID_MC_CORRECTIONS:
        raise ValueError(
            f"mc_correction must be one of {sorted(VALID_MC_CORRECTIONS)}"
        )
    stored_mc_correction = _canonical_mc_correction(mc_correction)
    if seed_count <= 0:
        raise ValueError("seed_count must be positive")
    if not (0.0 < float(alpha) < 1.0):
        raise ValueError("alpha must be in (0, 1)")
    if int(family_size) <= 0:
        raise ValueError("family_size must be positive")

    prereg_id = _new_prereg_id()
    locked_family_id = (
        str(family_id).strip() if family_id is not None else f"family_{prereg_id[7:]}"
    )
    if not locked_family_id or len(locked_family_id) > 128:
        raise ValueError("family_id must be 1-128 non-whitespace characters")
    with tx() as con:
        family_rows = con.execute(
            """
            SELECT family_size, alpha, mc_correction
            FROM ver_preregistrations
            WHERE family_id = ?
            """,
            (locked_family_id,),
        ).fetchall()
        if family_rows:
            exemplar = family_rows[0]
            if int(exemplar["family_size"]) != int(family_size):
                raise ValueError("family_size must match the locked family definition")
            if float(exemplar["alpha"]) != float(alpha):
                raise ValueError("alpha must match the locked family definition")
            if str(exemplar["mc_correction"]) != stored_mc_correction:
                raise ValueError("mc_correction must match the locked family definition")
            if len(family_rows) >= int(family_size):
                raise ValueError("preregistration family is already full")
        con.execute(
            """
            INSERT INTO ver_preregistrations(
              prereg_id, hypothesis_id, metric_name, direction, threshold,
              heldout_dataset, seed_count, alpha, mc_correction,
              family_id, family_size
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
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
                stored_mc_correction,
                locked_family_id,
                int(family_size),
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
                "mc_correction": stored_mc_correction,
                "family_id": locked_family_id,
                "family_size": int(family_size),
            },
        )
    return {
        "prereg_id": prereg_id,
        "hypothesis_id": hypothesis_id,
        "metric_name": normalize_claim(metric_name),
        "direction": direction,
        "threshold": threshold,
        "family_id": locked_family_id,
        "family_size": int(family_size),
        "status": "open",
    }


def resolve_preregistration(
    prereg_id: str,
    observed_value: float,
    observed_p_value: float | None = None,
) -> dict:
    """Compare a locked prereg against observed evidence and freeze its verdict.

    ``bonferroni`` operates on the family size frozen at registration time.
    Resolving other family members never relaxes the threshold.
    Old rows may still contain ``bh``; that legacy value resolves through
    the same Bonferroni-style path.
    ``observed_p_value`` is optional; when it is not supplied the verdict only
    uses the threshold.
    """
    with tx() as con:
        row = con.execute(
            """
            SELECT prereg_id, hypothesis_id, metric_name, direction, threshold,
                   alpha, mc_correction, family_id, family_size, status
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

        threshold = row["threshold"]
        alpha = float(row["alpha"])
        mc_correction = row["mc_correction"]
        family_size = max(1, int(row["family_size"]))

        if mc_correction in {"bonferroni", "bh"}:
            adjusted_alpha = _bonferroni_threshold(family_size, alpha)
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
            family_size,
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
                "family_id": row["family_id"],
                "family_size": family_size,
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
        "family_id": row["family_id"],
        "family_size": family_size,
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
                   family_id, family_size,
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
