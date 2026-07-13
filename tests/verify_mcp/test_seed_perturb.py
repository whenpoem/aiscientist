from __future__ import annotations

import json
import textwrap
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
        event = con.execute(
            """
            SELECT payload
            FROM cockpit_events
            WHERE kind = 'seed_run_recorded'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        manifest_row = con.execute(
            """
            SELECT provenance_id, seed_run_id, manifest_json, manifest_sha256
            FROM ver_run_manifests
            WHERE seed_run_id = ?
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
    assert json.loads(event["payload"])["run_id"] == result["run_id"]
    manifest = json.loads(manifest_row["manifest_json"])
    assert manifest_row["provenance_id"] == pin["provenance_id"]
    assert manifest_row["seed_run_id"] == result["run_id"]
    assert len(manifest_row["manifest_sha256"]) == 64
    assert manifest["seeds"] == [0, 1, 2]
    script_entries = [entry for entry in manifest["files"] if "script" in entry["roles"]]
    assert len(script_entries) == 1
    assert script_entries[0]["path"].endswith("seed_stable.py")
    assert script_entries[0]["sha256"] is not None


def test_seed_perturb_flags_noisy_runs(workspace):
    impl = workspace["verify_mcp.impl"]
    fixture = Path(__file__).with_name("fixtures") / "seed_noisy.py"

    result = impl.seed_perturb(script_path=str(fixture))

    assert result["ok"] is True
    assert result["verdict"] == "unstable"
    assert result["values"] == [0.7, 0.75, 0.8]
    assert result["mean_value"] == pytest.approx(0.75)
    assert result["std_value"] > 0.0


def test_seed_perturb_default_tolerance_allows_small_seed_drift(workspace, tmp_path):
    impl = workspace["verify_mcp.impl"]
    fixture = tmp_path / "seed_small_drift.py"
    fixture.write_text(
        textwrap.dedent(
            """
            import argparse

            parser = argparse.ArgumentParser()
            parser.add_argument("--seed", type=int, required=True)
            args = parser.parse_args()
            values = {0: 0.900, 1: 0.905, 2: 0.895}
            print(f"test accuracy: {values[args.seed]:.3f}")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = impl.seed_perturb(script_path=str(fixture))

    assert result["ok"] is True
    assert result["verdict"] == "stable"
    assert result["std_value"] == pytest.approx(0.005, abs=1e-6)
    assert result["stability_mode"] == "auto"
    assert result["stability_threshold"] == pytest.approx(0.01)


def test_seed_perturb_auto_tolerance_scales_large_metrics(workspace, tmp_path):
    impl = workspace["verify_mcp.impl"]
    fixture = tmp_path / "seed_large_metric.py"
    fixture.write_text(
        textwrap.dedent(
            """
            import argparse

            parser = argparse.ArgumentParser()
            parser.add_argument("--seed", type=int, required=True)
            args = parser.parse_args()
            values = {0: 100.0, 1: 100.5, 2: 99.5}
            print(f"score: {values[args.seed]:.1f}")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    auto = impl.seed_perturb(script_path=str(fixture))
    absolute = impl.seed_perturb(script_path=str(fixture), stability_mode="absolute")

    assert auto["ok"] is True
    assert auto["verdict"] == "stable"
    assert auto["stability_threshold"] == pytest.approx(1.0)
    assert absolute["verdict"] == "unstable"


def test_seed_perturb_falls_back_to_labelled_metric_parser(workspace, tmp_path):
    impl = workspace["verify_mcp.impl"]
    fixture = tmp_path / "seed_loss.py"
    fixture.write_text(
        textwrap.dedent(
            """
            import argparse

            parser = argparse.ArgumentParser()
            parser.add_argument("--seed", type=int, required=True)
            args = parser.parse_args()
            print(f"loss: {1.2 + args.seed * 0.001:.3f}")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = impl.seed_perturb(script_path=str(fixture))

    assert result["ok"] is True
    assert result["values"] == [1.2, 1.201, 1.202]


def test_seed_perturb_sets_pythonhashseed_by_default(workspace, tmp_path):
    impl = workspace["verify_mcp.impl"]
    fixture = tmp_path / "seed_from_env.py"
    fixture.write_text(
        textwrap.dedent(
            """
            import argparse
            import os

            parser = argparse.ArgumentParser()
            parser.add_argument("--seed", type=int, required=True)
            parser.parse_args()
            seed = int(os.environ["PYTHONHASHSEED"])
            values = {0: 0.81, 1: 0.82, 2: 0.83}
            print(f"test accuracy: {values[seed]:.2f}")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = impl.seed_perturb(script_path=str(fixture))

    assert result["ok"] is True
    assert result["seed_env"] == "PYTHONHASHSEED"
    assert result["values"] == [0.81, 0.82, 0.83]
