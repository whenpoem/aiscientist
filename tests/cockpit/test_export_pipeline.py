"""End-to-end tests for cockpit.export (v4.2.0a2 / ADR 0009)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _seed_proposition(workspace) -> str:
    """Return a freshly minted proposition id with a sample draft chain."""
    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition(
        "Sample mean is unbiased estimator of the population mean"
    )
    skel = prove_impl.propose_proof_skeleton(
        prop["node_id"],
        text="1. Apply linearity of expectation. 2. Done.",
    )
    prove_impl.register_proof_draft(
        skel["node_id"],
        draft_text=r"\textbf{Proof.} By linearity, $E[\bar X] = \mu$.",
    )
    return prop["node_id"]


def _redirect_reports(monkeypatch, tmp_path) -> Path:
    target = tmp_path / "reports-out"
    monkeypatch.setenv("RESEARCH_AGENT_REPORTS_DIR", str(target))
    return target


# ---------------------------------------------------------------------------
# pipeline.generate
# ---------------------------------------------------------------------------


def test_generate_writes_markdown_file_and_indexes(
    workspace, monkeypatch, tmp_path
):
    """A successful generate call produces a file, indexes it in
    cockpit_reports, and emits a `report_generated` event."""
    from cockpit.export import generate

    out_dir = _redirect_reports(monkeypatch, tmp_path)
    prop_id = _seed_proposition(workspace)

    paths = generate("closure", prop_id, formats=("md",))
    assert len(paths) == 1
    file_path = paths[0]
    assert file_path.exists()
    assert file_path.parent == out_dir
    assert file_path.suffix == ".md"
    body = file_path.read_text(encoding="utf-8")
    assert "# Closure:" in body
    assert prop_id in body

    # Index row landed in cockpit_reports.
    db = workspace["cockpit.db"]
    con = db.connect()
    try:
        row = con.execute(
            "SELECT kind, related_node_id, format, generated_by FROM cockpit_reports "
            "WHERE file_path = ?",
            (str(file_path),),
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    assert row["kind"] == "closure"
    assert row["related_node_id"] == prop_id
    assert row["format"] == "md"
    assert row["generated_by"] == "cockpit.export"

    # Event was emitted with the right payload.
    con = db.connect()
    try:
        ev = con.execute(
            "SELECT kind, payload FROM cockpit_events WHERE kind = ? "
            "ORDER BY id DESC LIMIT 1",
            ("report_generated",),
        ).fetchone()
    finally:
        con.close()
    assert ev is not None
    payload = json.loads(ev["payload"])
    assert payload["kind"] == "closure"
    assert payload["node_id"] == prop_id
    assert payload["format"] == "md"


def test_generate_emits_html_when_requested(workspace, monkeypatch, tmp_path):
    from cockpit.export import generate

    _redirect_reports(monkeypatch, tmp_path)
    prop_id = _seed_proposition(workspace)

    paths = generate("closure", prop_id, formats=("md", "html"))
    assert len(paths) == 2
    suffixes = {p.suffix for p in paths}
    assert suffixes == {".md", ".html"}
    for p in paths:
        body = p.read_text(encoding="utf-8")
        if p.suffix == ".html":
            assert "<!doctype html>" in body
            assert "Closure:" in body
        else:
            assert "# Closure:" in body


def test_generate_overwrites_on_rerun(workspace, monkeypatch, tmp_path):
    """Same (kind, node, format) overwrites in place. Only one row per file."""
    from cockpit.export import generate

    _redirect_reports(monkeypatch, tmp_path)
    prop_id = _seed_proposition(workspace)

    generate("closure", prop_id, formats=("md",))
    generate("closure", prop_id, formats=("md",))

    db = workspace["cockpit.db"]
    con = db.connect()
    try:
        count = con.execute(
            "SELECT COUNT(*) AS n FROM cockpit_reports WHERE kind = ? AND related_node_id = ?",
            ("closure", prop_id),
        ).fetchone()["n"]
    finally:
        con.close()
    assert int(count) == 1


def test_generate_rejects_unknown_kind(workspace, monkeypatch, tmp_path):
    from cockpit.export import generate

    _redirect_reports(monkeypatch, tmp_path)
    prop_id = _seed_proposition(workspace)
    with pytest.raises(ValueError, match="unknown report kind"):
        generate("nonsense", prop_id, formats=("md",))


def test_generate_rejects_unknown_format(workspace, monkeypatch, tmp_path):
    from cockpit.export import generate

    _redirect_reports(monkeypatch, tmp_path)
    prop_id = _seed_proposition(workspace)
    with pytest.raises(ValueError, match="unknown format"):
        generate("closure", prop_id, formats=("pdf",))


def test_generate_rejects_empty_formats(workspace, monkeypatch, tmp_path):
    from cockpit.export import generate

    _redirect_reports(monkeypatch, tmp_path)
    prop_id = _seed_proposition(workspace)
    with pytest.raises(ValueError, match="format"):
        generate("closure", prop_id, formats=())


def test_generate_rejects_unknown_node(workspace, monkeypatch, tmp_path):
    from cockpit.export import generate

    _redirect_reports(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="unknown node"):
        generate("closure", "prop_does_not_exist", formats=("md",))


def test_draft_report_rejects_non_proposition(workspace, monkeypatch, tmp_path):
    """build_draft is proposition-only; calling on a hypothesis raises."""
    from cockpit.export import generate

    _redirect_reports(monkeypatch, tmp_path)
    memory_impl = workspace["memory_mcp.impl"]
    hyp = memory_impl.propose_hypothesis("an empirical hypothesis")
    with pytest.raises(ValueError, match="draft"):
        generate("draft", hyp["node_id"], formats=("md",))


def test_hypothesis_closure_uses_current_verify_schema(
    workspace, monkeypatch, tmp_path
):
    """Regression: closure reports must query ver_preregistrations and
    ver_metric_pins using their real v4.2 column names."""
    from cockpit.export import generate

    _redirect_reports(monkeypatch, tmp_path)
    memory_impl = workspace["memory_mcp.impl"]
    verify_impl = workspace["verify_mcp.impl"]
    hyp = memory_impl.propose_hypothesis("empirical report target")
    verify_impl.preregister(
        hyp["node_id"],
        metric_name="accuracy",
        direction="higher_better",
        threshold=0.8,
    )
    verify_impl.pin_metric(
        claim="accuracy",
        value="0.82",
        session_id="demo-session",
        source_command="pytest",
    )

    [path] = generate("closure", hyp["node_id"], formats=("md",))
    body = path.read_text(encoding="utf-8")

    assert "Preregistrations" in body
    assert "accuracy" in body
    assert "Pinned metrics" in body
    assert "demo-session" in body


def test_kinds_for_node_kind_filters_proposition_vs_hypothesis():
    from cockpit.export.pipeline import kinds_for_node_kind

    prop_kinds = kinds_for_node_kind("proposition")
    assert set(prop_kinds) == {"closure", "draft", "diagnostic", "portfolio", "cascade"}

    hyp_kinds = kinds_for_node_kind("hypothesis")
    assert "closure" in hyp_kinds
    assert "cascade" in hyp_kinds
    assert "draft" not in hyp_kinds
    assert "diagnostic" not in hyp_kinds
    assert "portfolio" not in hyp_kinds
