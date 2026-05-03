"""Resource budget ledger tools (budget_check, budget_consume).

Owns the ``res_budget_ledger`` table. ``budget_consume`` is the only writer;
``budget_check`` is read-only and must address the same ``(scope, resource,
window)`` boundary that ``budget_consume`` writes, otherwise the two will
disagree at the limit.
"""

from __future__ import annotations

from verify_mcp.db import _connect, tx

from ._common import _emit_event

VALID_BUDGET_RESOURCES = {
    "wallclock_sec",
    "llm_tokens",
    "heldout_queries",
    "disk_mb",
}


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
