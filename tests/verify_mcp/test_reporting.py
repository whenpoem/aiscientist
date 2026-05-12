"""verify_mcp.export_report tool tests (v4.2.0a2 / ADR 0009)."""

from __future__ import annotations

import pytest


def test_export_report_returns_paths(workspace, monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_AGENT_REPORTS_DIR", str(tmp_path / "reports"))
    prove_impl = workspace["prove_mcp.impl"]
    verify_impl = workspace["verify_mcp.impl"]

    prop = prove_impl.propose_proposition("verify_mcp.export_report target")
    result = verify_impl.export_report(
        "closure", prop["node_id"], formats=("md",)
    )
    assert "paths" in result
    assert len(result["paths"]) == 1
    from pathlib import Path

    path = Path(result["paths"][0])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "Closure:" in body


def test_export_report_writes_with_verify_provenance(
    workspace, monkeypatch, tmp_path
):
    """The verify_mcp call stamps the index row with its own
    `generated_by` so the cockpit can distinguish reviewer-issued
    exports from interactive ones."""
    monkeypatch.setenv("RESEARCH_AGENT_REPORTS_DIR", str(tmp_path / "reports"))
    prove_impl = workspace["prove_mcp.impl"]
    verify_impl = workspace["verify_mcp.impl"]

    prop = prove_impl.propose_proposition("reviewer-side export attribution")
    verify_impl.export_report("closure", prop["node_id"], formats=("md",))

    db = workspace["cockpit.db"]
    con = db.connect()
    try:
        row = con.execute(
            "SELECT generated_by FROM cockpit_reports WHERE related_node_id = ?",
            (prop["node_id"],),
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    assert row["generated_by"] == "verify_mcp.export_report"


def test_export_report_rejects_unknown_kind(workspace, monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_AGENT_REPORTS_DIR", str(tmp_path / "reports"))
    verify_impl = workspace["verify_mcp.impl"]
    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition("unknown-kind target")
    with pytest.raises(ValueError):
        verify_impl.export_report("nonsense", prop["node_id"], formats=("md",))


def test_export_report_listed_in_tool_names(workspace):
    """TOOL_NAMES is the contract the FastMCP server reads from."""
    verify_impl = workspace["verify_mcp.impl"]
    assert "export_report" in verify_impl.TOOL_NAMES
