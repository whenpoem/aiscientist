"""Cross-process write-pressure checks for the shared SQLite boundary."""

from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def _prepare_worker(database: str) -> None:
    os.environ["RESEARCH_AGENT_DB_PATH"] = database
    os.environ["RESEARCH_AGENT_WORKSPACE_ROOT"] = str(
        Path(database).resolve().parent.parent
    )


def _budget_worker(arguments: tuple[str, int]) -> dict:
    database, index = arguments
    _prepare_worker(database)
    from claudescientist.runtime import cache_key
    from verify_mcp import db

    db._BOOTSTRAPPED.add(cache_key(Path(database)))
    from verify_mcp.tools.budget import budget_consume

    return budget_consume(
        scope="concurrent",
        resource="llm_tokens",
        amount=1.0,
        note=f"worker-{index}",
    )


def _bt_worker(arguments: tuple[str, str, str]) -> dict:
    database, winner_id, loser_id = arguments
    _prepare_worker(database)
    from claudescientist.runtime import cache_key
    from memory_mcp import db

    db._BOOTSTRAPPED.add(cache_key(Path(database)))
    from memory_mcp.tools.bt import update_bt_rating

    return update_bt_rating(
        winner_id=winner_id,
        loser_id=loser_id,
        source="llm_judge",
    )


def _provenance_worker(arguments: tuple[str, int]) -> dict:
    database, index = arguments
    _prepare_worker(database)
    from claudescientist.runtime import cache_key
    from verify_mcp import db

    db._BOOTSTRAPPED.add(cache_key(Path(database)))
    from verify_mcp.tools.provenance import pin_metric

    return pin_metric(
        claim=f"concurrent metric {index}",
        value=str(index),
        session_id=f"concurrent-session-{index}",
        note="cross-process pressure test",
    )


def _run_spawned(worker, arguments: list[tuple], *, max_workers: int = 8) -> list:
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=context) as executor:
        return list(executor.map(worker, arguments))


def test_concurrent_budget_consumption_never_exceeds_limit(workspace):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]
    database = str(db.state_db_path().resolve())
    impl.budget_consume(
        scope="concurrent",
        resource="llm_tokens",
        amount=0.0,
        limit_value=20.0,
    )

    outcomes = _run_spawned(
        _budget_worker,
        [(database, index) for index in range(32)],
    )

    assert sum(bool(outcome["ok"]) for outcome in outcomes) == 20
    assert sum(outcome.get("error") == "budget_exceeded" for outcome in outcomes) == 12
    con = db._connect()
    try:
        row = con.execute(
            """
            SELECT limit_value, used_value
            FROM res_budget_ledger
            WHERE scope = 'concurrent' AND resource = 'llm_tokens'
            """
        ).fetchone()
        exceeded_events = con.execute(
            "SELECT payload FROM cockpit_events WHERE kind = 'budget_exceeded'"
        ).fetchall()
    finally:
        con.close()
    assert float(row["limit_value"]) == 20.0
    assert float(row["used_value"]) == 20.0
    assert len(exceeded_events) == 12


def test_concurrent_bt_comparisons_preserve_every_ledger_entry(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]
    database = str(db.state_db_path().resolve())
    winner = impl.propose_hypothesis("Concurrent winner")["node_id"]
    loser = impl.propose_hypothesis("Concurrent loser")["node_id"]

    outcomes = _run_spawned(
        _bt_worker,
        [(database, winner, loser) for _ in range(16)],
    )

    assert len({int(outcome["comparison_id"]) for outcome in outcomes}) == 16
    assert all(outcome["fit"]["converged"] is True for outcome in outcomes)
    con = db._connect()
    try:
        comparison_count = con.execute(
            "SELECT COUNT(*) FROM mem_bt_comparisons"
        ).fetchone()[0]
        fit_state = con.execute(
            """
            SELECT comparison_count, converged, fit_error
            FROM mem_bt_fit_state WHERE kind = 'hypothesis'
            """
        ).fetchone()
        ratings = con.execute(
            """
            SELECT node_id, strength, n_comparisons
            FROM mem_bt_ratings WHERE node_id IN (?, ?)
            """,
            (winner, loser),
        ).fetchall()
        update_events = con.execute(
            "SELECT COUNT(*) FROM cockpit_events WHERE kind = 'bt_rating_updated'"
        ).fetchone()[0]
    finally:
        con.close()
    by_id = {str(row["node_id"]): row for row in ratings}
    assert comparison_count == 16
    assert fit_state["comparison_count"] == 16
    assert fit_state["converged"] == 1
    assert fit_state["fit_error"] == ""
    assert by_id[winner]["n_comparisons"] == 16
    assert by_id[loser]["n_comparisons"] == 16
    assert by_id[winner]["strength"] > by_id[loser]["strength"]
    assert update_events == 16


def test_concurrent_provenance_and_events_remain_one_to_one(workspace):
    db = workspace["verify_mcp.db"]
    database = str(db.state_db_path().resolve())

    outcomes = _run_spawned(
        _provenance_worker,
        [(database, index) for index in range(16)],
    )

    assert len({int(outcome["provenance_id"]) for outcome in outcomes}) == 16
    assert len({int(outcome["pin_id"]) for outcome in outcomes}) == 16
    con = db._connect()
    try:
        provenance_count = con.execute(
            "SELECT COUNT(*) FROM ver_provenance"
        ).fetchone()[0]
        dag_count = con.execute("SELECT COUNT(*) FROM ver_provenance_dag").fetchone()[0]
        manifest_count = con.execute("SELECT COUNT(*) FROM ver_run_manifests").fetchone()[0]
        pin_count = con.execute("SELECT COUNT(*) FROM ver_metric_pins").fetchone()[0]
        event_rows = con.execute(
            "SELECT payload FROM cockpit_events WHERE kind = 'claim_pinned'"
        ).fetchall()
    finally:
        con.close()

    event_claims = {json.loads(str(row["payload"]))["claim"] for row in event_rows}
    assert provenance_count == 16
    assert dag_count == 16
    assert manifest_count == 16
    assert pin_count == 16
    assert len(event_rows) == 16
    assert event_claims == {f"concurrent metric {index}" for index in range(16)}
