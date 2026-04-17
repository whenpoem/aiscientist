from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_seed_perturb_records_stable_runs(workspace):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]
    fixture = Path(__file__).with_name("fixtures") / "seed_stable.py"

    pin = impl.pin_metric(
        claim="test accuracy",
        value="0.875",
        session_id="sess-stable",
        source_command="uv run train.py",
        note="linked seed run",
    )
    result = impl.seed_perturb(
        script_path=str(fixture),
        metric_pin_id=pin["pin_id"],
    )

    assert result["ok"] is True
    assert result["verdict"] == "stable"
    assert result["metric_pin_id"] == pin["pin_id"]
    assert result["mean_value"] == pytest.approx(0.875)
    assert result["std_value"] == pytest.approx(0.0)
    assert result["values"] == [0.875, 0.875, 0.875]

    con = db._connect()
    try:
        row = con.execute(
            """
            SELECT script_path, seed_arg, seeds_json, metric_pattern, values_json,
                   mean_value, std_value, verdict, metric_pin_id
            FROM ver_seed_runs
            WHERE run_id = ?
            """,
            (result["run_id"],),
        ).fetchone()
    finally:
        con.close()

    assert row["script_path"].endswith("seed_stable.py")
    assert row["seed_arg"] == "--seed"
    assert json.loads(row["seeds_json"]) == [0, 1, 2]
    assert "test[_ ]acc" in row["metric_pattern"]
    assert json.loads(row["values_json"]) == [0.875, 0.875, 0.875]
    assert row["mean_value"] == pytest.approx(0.875)
    assert row["std_value"] == pytest.approx(0.0)
    assert row["verdict"] == "stable"
    assert row["metric_pin_id"] == pin["pin_id"]


def test_seed_perturb_flags_noisy_runs(workspace):
    impl = workspace["verify_mcp.impl"]
    fixture = Path(__file__).with_name("fixtures") / "seed_noisy.py"

    result = impl.seed_perturb(script_path=str(fixture))

    assert result["ok"] is True
    assert result["verdict"] == "unstable"
    assert result["values"] == [0.7, 0.75, 0.8]
    assert result["mean_value"] == pytest.approx(0.75)
    assert result["std_value"] > 0.0
