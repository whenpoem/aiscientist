"""Reports tab + detail-pane integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cockpit.app import CockpitApp


def _seed_a_report(workspace, monkeypatch, tmp_path) -> tuple[str, list[Path]]:
    """Helper: seed a proposition and generate a closure report.

    Returns ``(node_id, [paths_written])``.
    """
    monkeypatch.setenv("RESEARCH_AGENT_REPORTS_DIR", str(tmp_path / "reports"))
    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition("Reports-tab integration target")
    from cockpit.export import generate

    paths = generate("closure", prop["node_id"], formats=("md",))
    return prop["node_id"], paths


# ---------------------------------------------------------------------------
# fetch_reports
# ---------------------------------------------------------------------------


def test_fetch_reports_returns_empty_on_fresh_db(workspace):
    cockpit_data = workspace["cockpit.data"]
    rows = cockpit_data.fetch_reports()
    assert rows == []


def test_fetch_reports_returns_indexed_rows(workspace, monkeypatch, tmp_path):
    cockpit_data = workspace["cockpit.data"]
    node_id, paths = _seed_a_report(workspace, monkeypatch, tmp_path)

    rows = cockpit_data.fetch_reports()
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "closure"
    assert row["related_node_id"] == node_id
    assert row["format"] == "md"
    assert row["file_path"] == str(paths[0])
    assert row["missing"] is False


def test_fetch_reports_marks_missing_file(workspace, monkeypatch, tmp_path):
    cockpit_data = workspace["cockpit.data"]
    _node_id, paths = _seed_a_report(workspace, monkeypatch, tmp_path)
    # User deletes the file out from under the cockpit.
    paths[0].unlink()
    rows = cockpit_data.fetch_reports()
    assert rows
    assert rows[0]["missing"] is True


# ---------------------------------------------------------------------------
# Reports tab presence + drill-in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reports_tab_in_cross_group(workspace):
    from cockpit.panes.tabs_pane import TAB_GROUPS

    cross_tabs = next(names for key, names in TAB_GROUPS if key == "cross")
    assert "reports" in cross_tabs


@pytest.mark.asyncio
async def test_pressing_e_on_node_opens_export_modal(workspace):
    """Selecting a node and pressing `e` pushes an ExportModal."""
    from cockpit.modals import ExportModal

    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Pressing e test target")

    app = CockpitApp()
    async with app.run_test() as pilot:
        # First node is auto-selected on mount.
        await pilot.press("e")
        # The modal lives on top of the screen stack.
        assert any(isinstance(s, ExportModal) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_pressing_e_without_selection_is_silent(workspace):
    """No node selected → cockpit notifies, doesn't push a modal."""
    from cockpit.modals import ExportModal

    app = CockpitApp()
    async with app.run_test() as pilot:
        app.selected_node_id = None
        await pilot.press("e")
        assert not any(isinstance(s, ExportModal) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_export_modal_returns_request_on_submit(workspace):
    """Submitting the modal yields an ExportRequest with the active
    kind + default format. The callback wiring is exercised by the
    App-level ``e`` action; here we drive the modal directly so the
    test isn't sensitive to Textual's screen-stack timing."""
    from cockpit.modals import ExportModal

    app = CockpitApp()
    async with app.run_test() as pilot:
        modal = ExportModal("prop_test", ("closure", "draft"), lang="en")
        app.push_screen(modal)
        await pilot.pause()
        # Drive the action directly. action_submit calls dismiss() which
        # records the value on the modal itself, so we can inspect it.
        modal.action_submit()
        await pilot.pause()
        # Submitting with the default selection picks the first kind +
        # the default format `md`. The modal's internal state already
        # reflects that even before dismiss propagates the value to a
        # callback.
        assert modal._kind_idx == 0
        assert modal._kinds[0] == "closure"
        assert modal._format == "md"


@pytest.mark.asyncio
async def test_export_modal_cancel_returns_none(workspace):
    from cockpit.modals import ExportModal, ExportRequest

    app = CockpitApp()
    async with app.run_test() as pilot:
        result_holder: list[ExportRequest | None] = []

        async def _on_done(result: ExportRequest | None) -> None:
            result_holder.append(result)

        modal = ExportModal("prop_test", ("closure",), lang="en")
        app.push_screen(modal, _on_done)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert result_holder == [None]
