from __future__ import annotations

import json


def test_record_provenance_without_explicit_inputs_still_records_run_manifest(workspace):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]

    result = impl.record_provenance(
        claim="acc",
        value="0.81",
        session_id="session-1",
        source_command="python train.py",
    )
    assert "dag" in result
    assert "run_manifest" in result

    con = db._connect()
    try:
        rows = con.execute("SELECT COUNT(*) FROM ver_provenance_dag").fetchone()
        manifests = con.execute("SELECT COUNT(*) FROM ver_run_manifests").fetchone()
    finally:
        con.close()
    assert rows[0] == 1
    assert manifests[0] == 1


def test_record_provenance_with_inputs_writes_dag(workspace, tmp_path):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]

    payload = tmp_path / "dataset.csv"
    payload.write_text("x,y\n1,2\n", encoding="utf-8")

    result = impl.record_provenance(
        claim="acc",
        value="0.91",
        session_id="session-1",
        source_command="python train.py --data dataset.csv",
        input_files=[str(payload)],
    )
    assert "dag" in result
    dag = result["dag"]
    assert dag["input_hashes"][0]["path"] == str(payload)
    assert dag["input_hashes"][0]["sha256"] is not None

    con = db._connect()
    try:
        row = con.execute(
            "SELECT input_hashes, output_hash, stale "
            "FROM ver_provenance_dag WHERE prov_id = ?",
            (result["provenance_id"],),
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    stored = json.loads(row["input_hashes"])
    assert stored[0]["path"] == str(payload)
    assert row["stale"] == 0


def test_refresh_claim_marks_stale_when_input_changes(workspace, tmp_path):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]

    payload = tmp_path / "dataset.csv"
    payload.write_text("x,y\n1,2\n", encoding="utf-8")

    record = impl.record_provenance(
        claim="acc",
        value="0.91",
        session_id="session-1",
        source_command="python train.py",
        input_files=[str(payload)],
    )

    fresh = impl.refresh_claim("acc")
    assert fresh["status"] == "fresh"
    assert fresh["stale_count"] == 0

    payload.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")

    stale = impl.refresh_claim("acc")
    assert stale["status"] == "stale"
    assert stale["stale_count"] == 1
    assert stale["checked"][0]["prov_id"] == record["provenance_id"]
    assert stale["checked"][0]["mismatched"][0]["path"] == str(payload)

    con = db._connect()
    try:
        flag = con.execute(
            "SELECT stale FROM ver_provenance_dag WHERE prov_id = ?",
            (record["provenance_id"],),
        ).fetchone()
    finally:
        con.close()
    assert flag["stale"] == 1


def test_refresh_claim_marks_stale_when_experiment_code_changes(workspace, tmp_path):
    impl = workspace["verify_mcp.impl"]
    script = tmp_path / "train.py"
    script.write_text("print('accuracy: 0.80')\n", encoding="utf-8")

    result = impl.record_provenance(
        claim="accuracy",
        value="0.80",
        session_id="session-code",
        source_command=f"python {script}",
    )
    assert result["dag"]["input_hashes"]
    assert any(
        entry["path"] == str(script) for entry in result["dag"]["input_hashes"]
    )

    script.write_text("print('accuracy: 0.95')\n", encoding="utf-8")
    stale = impl.refresh_claim("accuracy")
    assert stale["status"] == "stale"
    assert stale["checked"][0]["manifest_mismatched"]


def test_refresh_claim_emits_cockpit_event(workspace, tmp_path):
    impl = workspace["verify_mcp.impl"]
    cockpit_data = workspace.get("cockpit.data")
    if cockpit_data is None:
        return

    payload = tmp_path / "dataset.csv"
    payload.write_text("alpha", encoding="utf-8")

    impl.record_provenance(
        claim="acc",
        value="0.5",
        session_id="session-1",
        input_files=[str(payload)],
    )

    payload.write_text("beta", encoding="utf-8")
    impl.refresh_claim("acc")

    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "prov_dag_stale" in kinds


def test_refresh_claim_returns_missing_for_unknown_claim(workspace):
    impl = workspace["verify_mcp.impl"]
    result = impl.refresh_claim("nonexistent_claim")
    assert result["status"] == "missing"
    assert result["checked"] == []


def test_refresh_claim_handles_legacy_rows_without_dag(workspace):
    impl = workspace["verify_mcp.impl"]
    db = workspace["verify_mcp.db"]
    con = db._connect()
    try:
        con.execute(
            """
            INSERT INTO ver_provenance(claim, value, session_id, source_command)
            VALUES('acc', '0.7', 'legacy-session', 'python train.py')
            """
        )
    finally:
        con.close()
    result = impl.refresh_claim("acc")
    # No DAG row means we cannot judge staleness; it is fresh-but-unchecked,
    # not proof that upstream files are unchanged.
    assert result["status"] == "fresh"
    assert result["unchecked_count"] == 1
    assert result["checked"][0]["unchecked"] is True
    assert result["checked"][0]["reason"] == "no_dag_entry"
