from __future__ import annotations

import importlib
import inspect
from pathlib import Path


def test_pin_metric_creates_pin_and_linked_provenance(workspace):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]

    result = impl.pin_metric(
        claim="Validation Accuracy",
        value="91.2%",
        session_id="sess-1",
        source_command="uv run train.py",
        note="best checkpoint",
    )

    assert result["pinned"] is True
    evidence = impl.check_provenance("validation accuracy")
    assert evidence["status"] == "found"
    assert evidence["evidence"][0]["value"] == "91.2%"
    assert evidence["pins"][0]["note"] == "best checkpoint"
    assert evidence["pins"][0]["provenance_id"] == result["provenance_id"]

    con = db._connect()
    try:
        stored = con.execute(
            "SELECT claim, value, note FROM ver_metric_pins WHERE id = ?",
            (result["pin_id"],),
        ).fetchone()
    finally:
        con.close()

    assert dict(stored) == {
        "claim": "validation accuracy",
        "value": "91.2%",
        "note": "best checkpoint",
    }


def test_record_provenance_normalizes_claims(workspace):
    impl = workspace["verify_mcp.impl"]

    record = impl.record_provenance(
        claim="  Test   Loss  ",
        value="0.123",
        session_id="sess-2",
        source_command="uv run eval.py",
    )

    assert record["recorded"] is True
    evidence = impl.check_provenance("test loss")
    assert evidence["status"] == "found"
    assert evidence["evidence"][0]["claim"] == "test loss"
    assert evidence["evidence"][0]["value"] == "0.123"


def test_check_provenance_includes_seed_verdict_for_pins(workspace):
    impl = workspace["verify_mcp.impl"]
    fixture = Path(__file__).with_name("fixtures") / "seed_stable.py"

    pin = impl.pin_metric(
        claim="test accuracy",
        value="0.875",
        session_id="sess-seed",
        source_command=f"python {fixture}",
    )
    seed_run = impl.seed_perturb(
        script_path=str(fixture),
        metric_pin_id=pin["pin_id"],
    )
    assert seed_run["ok"] is True

    evidence = impl.check_provenance("test accuracy")
    assert evidence["status"] == "found"
    assert evidence["pins"][0]["id"] == pin["pin_id"]
    assert evidence["pins"][0]["pin_id"] == pin["pin_id"]
    assert evidence["pins"][0]["seed_verdict"] == "stable"
    assert evidence["pins"][0]["seed_run_count"] == 1
    assert evidence["pins"][0]["latest_seed_run_id"] == seed_run["run_id"]


def test_dev_server_wrappers_preserve_impl_signatures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    impl = importlib.reload(importlib.import_module("verify_mcp.impl"))
    dev_server = importlib.reload(importlib.import_module("verify_mcp.dev_server"))

    assert inspect.signature(dev_server.leakage_check) == inspect.signature(
        impl.leakage_check
    )
    assert inspect.signature(dev_server.record_provenance) == inspect.signature(
        impl.record_provenance
    )
    assert inspect.signature(dev_server.check_provenance) == inspect.signature(
        impl.check_provenance
    )
    assert inspect.signature(dev_server.pin_metric) == inspect.signature(impl.pin_metric)


def test_memory_dev_server_wrappers_preserve_impl_signatures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    impl = importlib.reload(importlib.import_module("memory_mcp.impl"))
    dev_server = importlib.reload(importlib.import_module("memory_mcp.dev_server"))

    assert inspect.signature(dev_server.propose_hypothesis) == inspect.signature(
        impl.propose_hypothesis
    )
    assert inspect.signature(dev_server.record_failure) == inspect.signature(
        impl.record_failure
    )
    assert inspect.signature(dev_server.snapshot) == inspect.signature(impl.snapshot)
