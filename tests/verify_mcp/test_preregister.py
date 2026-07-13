from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def _concurrent_preregister_worker(arguments: tuple[str, int, int]) -> str:
    database, family_size, index = arguments
    os.environ["RESEARCH_AGENT_DB_PATH"] = database
    from claudescientist.runtime import cache_key
    from verify_mcp import db
    from verify_mcp.tools.prereg import preregister

    db._BOOTSTRAPPED.add(cache_key(Path(database)))
    try:
        preregister(
            hypothesis_id=f"hyp_concurrent_{index}",
            metric_name=f"metric_{index}",
            direction="higher_better",
            threshold=0.5,
            family_id="concurrent_family",
            family_size=family_size,
        )
    except ValueError as exc:
        return str(exc)
    return "ok"


def test_preregister_locks_and_lists(workspace):
    impl = workspace["verify_mcp.impl"]

    result = impl.preregister(
        hypothesis_id="hyp_x",
        metric_name="ACC",
        direction="higher_better",
        threshold=0.85,
        seed_count=3,
        alpha=0.05,
    )
    assert result["status"] == "open"
    assert result["prereg_id"].startswith("prereg_")

    rows = impl.list_preregistrations()
    assert len(rows) == 1
    assert rows[0]["status"] == "open"
    assert rows[0]["metric_name"] == "acc"  # normalized
    assert rows[0]["mc_correction"] == "bonferroni"
    assert rows[0]["family_id"] == result["family_id"]
    assert rows[0]["family_size"] == 1


def test_preregister_validates_inputs(workspace):
    impl = workspace["verify_mcp.impl"]

    raised = False
    try:
        impl.preregister(
            hypothesis_id=None,
            metric_name="acc",
            direction="sideways",
            threshold=0.5,
        )
    except ValueError:
        raised = True
    assert raised

    raised = False
    try:
        impl.preregister(
            hypothesis_id=None,
            metric_name="acc",
            direction="higher_better",
            threshold=0.5,
            mc_correction="hidden",
        )
    except ValueError:
        raised = True
    assert raised

    raised = False
    try:
        impl.preregister(
            hypothesis_id=None,
            metric_name="acc",
            direction="higher_better",
            threshold=0.5,
            alpha=1.5,
        )
    except ValueError:
        raised = True
    assert raised


def test_resolve_marks_met_when_threshold_satisfied(workspace):
    impl = workspace["verify_mcp.impl"]

    locked = impl.preregister(
        hypothesis_id="hyp_a",
        metric_name="acc",
        direction="higher_better",
        threshold=0.8,
    )
    resolved = impl.resolve_preregistration(
        prereg_id=locked["prereg_id"],
        observed_value=0.91,
        observed_p_value=0.01,
    )
    assert resolved["ok"] is True
    assert resolved["status"] == "met"
    assert resolved["observed_p_value"] == 0.01
    assert resolved["adjusted_p_value"] == 0.01
    assert resolved["adjusted_alpha"] <= 0.05

    stored = impl.list_preregistrations()[0]
    assert stored["observed_p_value"] == 0.01
    assert stored["adjusted_p_value"] == 0.01


def test_resolve_marks_missed_when_below_threshold(workspace):
    impl = workspace["verify_mcp.impl"]

    locked = impl.preregister(
        hypothesis_id="hyp_b",
        metric_name="acc",
        direction="higher_better",
        threshold=0.95,
    )
    resolved = impl.resolve_preregistration(
        prereg_id=locked["prereg_id"],
        observed_value=0.90,
    )
    assert resolved["status"] == "missed"


def test_bonferroni_uses_fixed_family_size_after_rows_resolve(workspace):
    impl = workspace["verify_mcp.impl"]

    locked = []
    for idx in range(4):
        locked.append(
            impl.preregister(
                hypothesis_id=f"hyp_{idx}",
                metric_name=f"acc_{idx}",
                direction="higher_better",
                threshold=0.5,
                alpha=0.05,
                mc_correction="bonferroni",
                family_id="primary_metrics",
                family_size=4,
            )
        )

    first = impl.resolve_preregistration(
        prereg_id=locked[0]["prereg_id"],
        observed_value=0.6,
        observed_p_value=0.04,
    )
    # The locked family of four uses alpha 0.05/4 = 0.0125.
    assert first["status"] == "missed"
    assert first["adjusted_p_value"] == 0.16
    assert first["adjusted_alpha"] <= 0.05 / 4 + 1e-9

    last = impl.resolve_preregistration(
        prereg_id=locked[1]["prereg_id"],
        observed_value=0.6,
        observed_p_value=0.001,
    )
    # Resolving one row does not relax the remaining family's correction.
    assert last["status"] == "met"
    assert last["adjusted_p_value"] == 0.004
    assert last["adjusted_alpha"] == 0.0125


def test_fixed_family_prevents_sequential_bonferroni_relaxation(workspace):
    impl = workspace["verify_mcp.impl"]
    first = impl.preregister(
        hypothesis_id="hyp_a",
        metric_name="acc_a",
        direction="higher_better",
        threshold=0.5,
        family_id="two_tests",
        family_size=2,
    )
    second = impl.preregister(
        hypothesis_id="hyp_b",
        metric_name="acc_b",
        direction="higher_better",
        threshold=0.5,
        family_id="two_tests",
        family_size=2,
    )

    result_a = impl.resolve_preregistration(first["prereg_id"], 0.6, 0.04)
    result_b = impl.resolve_preregistration(second["prereg_id"], 0.6, 0.04)
    assert result_a["status"] == "missed"
    assert result_b["status"] == "missed"
    assert result_a["adjusted_alpha"] == result_b["adjusted_alpha"] == 0.025
    assert result_a["adjusted_p_value"] == result_b["adjusted_p_value"] == 0.08


def test_preregistration_family_definition_is_immutable(workspace):
    impl = workspace["verify_mcp.impl"]
    impl.preregister(
        hypothesis_id="hyp_a",
        metric_name="acc_a",
        direction="higher_better",
        threshold=0.5,
        family_id="locked_family",
        family_size=2,
    )
    try:
        impl.preregister(
            hypothesis_id="hyp_b",
            metric_name="acc_b",
            direction="higher_better",
            threshold=0.5,
            family_id="locked_family",
            family_size=3,
        )
    except ValueError as exc:
        assert "family_size" in str(exc)
    else:
        raise AssertionError("expected immutable family definition")


def test_concurrent_processes_cannot_overfill_fixed_family(workspace):
    db = workspace["verify_mcp.db"]
    database = str(db.state_db_path().resolve())
    family_size = 4
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=8, mp_context=context) as executor:
        outcomes = list(
            executor.map(
                _concurrent_preregister_worker,
                [(database, family_size, index) for index in range(12)],
            )
        )

    assert outcomes.count("ok") == family_size
    assert outcomes.count("preregistration family is already full") == 8

    con = db._connect()
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM ver_preregistrations WHERE family_id = ?",
            ("concurrent_family",),
        ).fetchone()[0]
    finally:
        con.close()
    assert count == family_size


def test_legacy_bh_alias_canonicalizes_for_new_rows(workspace):
    impl = workspace["verify_mcp.impl"]

    locked = impl.preregister(
        hypothesis_id="hyp_old",
        metric_name="acc",
        direction="higher_better",
        threshold=0.5,
        mc_correction="bh",
    )
    row = impl.list_preregistrations()[0]
    assert row["prereg_id"] == locked["prereg_id"]
    assert row["mc_correction"] == "bonferroni"


def test_legacy_bh_rows_still_resolve(workspace):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]

    locked = impl.preregister(
        hypothesis_id="hyp_old_db",
        metric_name="acc",
        direction="higher_better",
        threshold=0.5,
    )
    con = db._connect()
    try:
        con.execute(
            "UPDATE ver_preregistrations SET mc_correction = 'bh' WHERE prereg_id = ?",
            (locked["prereg_id"],),
        )
    finally:
        con.close()

    resolved = impl.resolve_preregistration(
        prereg_id=locked["prereg_id"],
        observed_value=0.6,
        observed_p_value=0.01,
    )
    assert resolved["ok"] is True
    assert resolved["status"] == "met"
    assert resolved["mc_correction"] == "bh"


def test_double_resolve_returns_already_resolved(workspace):
    impl = workspace["verify_mcp.impl"]
    locked = impl.preregister(
        hypothesis_id=None,
        metric_name="acc",
        direction="higher_better",
        threshold=0.5,
    )
    impl.resolve_preregistration(prereg_id=locked["prereg_id"], observed_value=0.6)
    again = impl.resolve_preregistration(
        prereg_id=locked["prereg_id"], observed_value=0.6
    )
    assert again["ok"] is False
    assert again["error"] == "already_resolved"


def test_unknown_prereg_returns_unknown_error(workspace):
    impl = workspace["verify_mcp.impl"]
    result = impl.resolve_preregistration(prereg_id="prereg_missing", observed_value=0.5)
    assert result["ok"] is False
    assert result["error"] == "unknown_prereg"


def test_prereg_emits_cockpit_events(workspace):
    impl = workspace["verify_mcp.impl"]
    cockpit_data = workspace.get("cockpit.data")
    if cockpit_data is None:
        return
    locked = impl.preregister(
        hypothesis_id="hyp_x",
        metric_name="acc",
        direction="higher_better",
        threshold=0.5,
    )
    impl.resolve_preregistration(prereg_id=locked["prereg_id"], observed_value=0.7)
    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "prereg_locked" in kinds
    assert "prereg_resolved" in kinds
