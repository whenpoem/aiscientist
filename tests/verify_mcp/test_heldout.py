from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_dataset(root: Path) -> Path:
    dataset = root / "raw_dataset"
    dataset.mkdir()
    (dataset / "labels.csv").write_text("id,label\n1,cat\n2,dog\n", encoding="utf-8")
    (dataset / "features.csv").write_text("id,x\n1,0.1\n2,0.2\n", encoding="utf-8")
    return dataset


def test_heldout_register_query_and_exhaust_budget(workspace, monkeypatch, tmp_path):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]
    import claudescientist.heldout as heldout

    monkeypatch.setenv("RESEARCH_AGENT_HELDOUT_DIR", str(tmp_path / "heldout"))
    dataset = _make_dataset(tmp_path)
    model = Path(__file__).with_name("fixtures") / "heldout_model.py"

    exit_code = heldout.main(["register", "mnist-test", str(dataset)])
    assert exit_code == 0

    heldout_root = tmp_path / "heldout" / "mnist-test"
    assert heldout_root.exists()
    assert (heldout_root / "manifest.json").exists()
    assert (tmp_path / "raw_dataset.heldout-pointer").exists()

    first = impl.query_heldout("mnist-test", str(model), batch_size=1)
    assert first["ok"] is True
    assert first["metric_value"] == pytest.approx(0.82)
    assert first["budget_used"] == 1
    assert first["remaining_budget"] == 4

    for _ in range(4):
        result = impl.query_heldout("mnist-test", str(model), batch_size=1)
        assert result["ok"] is True

    exhausted = impl.query_heldout("mnist-test", str(model), batch_size=1)
    assert exhausted == {
        "ok": False,
        "error": "budget_exceeded",
        "dataset": "mnist-test",
        "budget_total": 5,
        "budget_used": 5,
    }

    con = db._connect()
    try:
        row = con.execute(
            """
            SELECT budget_used, budget_total, manifest_sha256
            FROM ver_heldout_budgets
            WHERE dataset = ?
            """,
            ("mnist-test",),
        ).fetchone()
        queries = con.execute(
            "SELECT COUNT(*) AS n FROM ver_heldout_queries WHERE dataset = ?",
            ("mnist-test",),
        ).fetchone()
    finally:
        con.close()

    assert row["budget_used"] == 5
    assert row["budget_total"] == 5
    assert queries["n"] == 5

    inspect_result = heldout.main(["inspect", "mnist-test"])
    assert inspect_result == 0


def test_heldout_manifest_drift_blocks_query(workspace, monkeypatch, tmp_path):
    impl = workspace["verify_mcp.impl"]
    import claudescientist.heldout as heldout

    monkeypatch.setenv("RESEARCH_AGENT_HELDOUT_DIR", str(tmp_path / "heldout"))
    dataset = _make_dataset(tmp_path)
    model = Path(__file__).with_name("fixtures") / "heldout_model.py"

    assert heldout.main(["register", "mnist-drift", str(dataset)]) == 0
    manifest_path = tmp_path / "heldout" / "mnist-drift" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_sha256"] = "tampered"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    result = impl.query_heldout("mnist-drift", str(model))

    assert result == {"ok": False, "error": "manifest_drift", "dataset": "mnist-drift"}
