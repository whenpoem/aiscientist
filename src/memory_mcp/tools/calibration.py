"""Agent calibration tools: record per-bucket and emit a reliability report."""

from __future__ import annotations

from memory_mcp.db import _connect, tx

CALIBRATION_BUCKETS = (0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95)


def _bucket_predicted_p(value: float) -> float:
    if not (0.0 <= value <= 1.0):
        raise ValueError("predicted_p must be in [0, 1]")
    closest = min(CALIBRATION_BUCKETS, key=lambda bucket: abs(bucket - float(value)))
    return float(closest)


def record_calibration(
    agent_name: str,
    predicted_p: float,
    realized_outcome: int,
) -> dict:
    """Append one calibration data point for an agent.

    ``predicted_p`` is bucketed to the nearest CALIBRATION_BUCKETS centre so
    the reliability diagram has predictable bins. ``realized_outcome`` must
    be 0 or 1.
    """
    if realized_outcome not in (0, 1):
        raise ValueError("realized_outcome must be 0 or 1")
    if not agent_name.strip():
        raise ValueError("agent_name must be non-empty")
    bucket = _bucket_predicted_p(float(predicted_p))
    with tx() as con:
        con.execute(
            """
            INSERT INTO meta_calibration(agent_name, predicted_p, realized_outcome, n)
            VALUES(?, ?, ?, 1)
            ON CONFLICT(agent_name, predicted_p, realized_outcome) DO UPDATE SET
              n = n + 1
            """,
            (agent_name.strip(), bucket, int(realized_outcome)),
        )
    return {
        "agent_name": agent_name.strip(),
        "bucket": bucket,
        "outcome": int(realized_outcome),
    }


def calibration_report(agent_name: str | None = None) -> dict:
    """Return reliability-diagram buckets and a Brier-score summary.

    When ``agent_name`` is ``None`` the report aggregates across every agent.
    """
    where = "WHERE agent_name = ?" if agent_name else ""
    params: tuple = (agent_name.strip(),) if agent_name else ()
    con = _connect()
    try:
        rows = con.execute(
            f"""
            SELECT agent_name, predicted_p, realized_outcome, n
            FROM meta_calibration
            {where}
            ORDER BY predicted_p ASC
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    buckets: dict[float, dict[str, float]] = {}
    weighted_brier_num = 0.0
    weighted_brier_den = 0
    for row in rows:
        p = float(row["predicted_p"])
        outcome = int(row["realized_outcome"])
        n = int(row["n"])
        entry = buckets.setdefault(
            p,
            {"predicted_p": p, "n": 0, "wins": 0, "observed_p": 0.0},
        )
        entry["n"] += n
        if outcome == 1:
            entry["wins"] += n
        weighted_brier_num += n * (p - outcome) ** 2
        weighted_brier_den += n

    diagram = []
    for p in sorted(buckets):
        entry = buckets[p]
        observed = entry["wins"] / entry["n"] if entry["n"] else 0.0
        entry["observed_p"] = round(observed, 6)
        diagram.append(entry)

    drift = max(
        (abs(entry["observed_p"] - entry["predicted_p"]) for entry in diagram),
        default=0.0,
    )
    brier = (
        weighted_brier_num / weighted_brier_den if weighted_brier_den else 0.0
    )

    return {
        "agent_name": agent_name,
        "buckets": diagram,
        "brier_score": round(brier, 6),
        "max_drift": round(drift, 6),
        "total_predictions": int(weighted_brier_den),
    }
