"""Phase E regression tests.

Covers:

- E1: :mod:`cockpit.text_width` cell-width helpers (CJK width, padding,
  truncation).
- E2: cockpit_events provenance column — schema migration, ``source``
  round-trips through ``record_event`` and the MCP-server tools, the
  Detail pane renders an "emitted by" line.
- E3: bookmarks — settings list round-trip, ``b`` toggle action,
  ``B`` modal smoke test, tree-pane indicator.
- E4: timeline strip — visibility toggle, severity-glyph rendering.
"""

from __future__ import annotations

import pytest

from cockpit import data as cockpit_data
from cockpit.app import CockpitApp

# ---------------------------------------------------------------------------
# E1: text_width
# ---------------------------------------------------------------------------


def test_cell_width_basic_ascii():
    from cockpit.text_width import cell_width

    assert cell_width("hello") == 5
    assert cell_width("") == 0


def test_cell_width_cjk_doubles():
    from cockpit.text_width import cell_width

    # Each Chinese ideograph is 2 monospace cells in every terminal we
    # target. Mixed strings sum correctly.
    assert cell_width("研究") == 4
    assert cell_width("hi 研究 state") == 3 + 4 + 6  # "hi " + "研究" + " state"


def test_cell_width_combining_marks_zero_cells():
    from cockpit.text_width import cell_width

    # "é" composed as e + combining acute should still be 1 cell. Use
    # NFD-decomposed form so the combining mark stands separately.
    decomposed = "é"
    assert cell_width(decomposed) == 1


def test_pad_to_width_handles_cjk():
    from cockpit.text_width import cell_width, pad_to_width

    out = pad_to_width("研究", 10, side="right")
    assert cell_width(out) == 10
    out_left = pad_to_width("研究", 10, side="left")
    assert cell_width(out_left) == 10
    assert out_left.endswith("研究")
    assert out.startswith("研究")


def test_truncate_to_width_appends_ellipsis():
    from cockpit.text_width import cell_width, truncate_to_width

    long = "abcdefghijk"
    out = truncate_to_width(long, 5)
    assert cell_width(out) <= 5
    assert "…" in out


def test_truncate_to_width_handles_cjk():
    from cockpit.text_width import cell_width, truncate_to_width

    out = truncate_to_width("研究状态报告", 6)
    # 3 CJK chars (6 cells) fit; the 4th would push to 8.
    # With "…" the budget shrinks: budget=5, so "研究" (4) + "…" = 5.
    assert cell_width(out) <= 6
    assert out.endswith("…")


# ---------------------------------------------------------------------------
# E2: provenance
# ---------------------------------------------------------------------------


def test_cockpit_events_table_has_source_column(workspace):
    """The Phase E migration must add the ``source`` column to fresh
    *and* pre-existing DBs."""
    from cockpit.db import connect

    con = connect()
    try:
        columns = {row["name"] for row in con.execute("PRAGMA table_info(cockpit_events)")}
        assert "source" in columns
    finally:
        con.close()


def test_runtime_emit_event_adds_source_column_to_old_event_table(tmp_path):
    """MCP tools write through runtime.emit_cockpit_event directly."""
    from claudescientist.runtime import connect_sqlite, emit_cockpit_event

    con = connect_sqlite(tmp_path / "state.db")
    try:
        con.execute(
            """
            CREATE TABLE cockpit_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL,
              payload TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        event_id = emit_cockpit_event(
            con,
            "note",
            {"text": "from old schema"},
            source="verify_mcp",
        )
        columns = {row["name"] for row in con.execute("PRAGMA table_info(cockpit_events)")}
        assert "source" in columns
        row = con.execute(
            "SELECT source FROM cockpit_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        assert row["source"] == "verify_mcp"
    finally:
        con.close()


def test_record_event_persists_source(workspace):
    """``record_event(..., source=...)`` round-trips through SQL."""
    event_id = cockpit_data.record_event(
        "note", {"text": "smoke"}, source="cockpit_user"
    )
    rows = cockpit_data.fetch_new_events(event_id - 1)
    assert rows, "expected the just-inserted event back"
    matching = [r for r in rows if int(r["id"]) == event_id]
    assert matching, "fetch_new_events should have returned the inserted row"
    assert matching[0]["source"] == "cockpit_user"


def test_record_event_default_source_is_null(workspace):
    """Legacy callers that pass nothing leave source=NULL.

    The Phase E migration is additive — pre-Phase-E callers continue
    to work and their rows simply render as ``unknown`` in the UI.
    """
    event_id = cockpit_data.record_event("note", {"text": "no source"})
    rows = cockpit_data.fetch_new_events(event_id - 1)
    matching = [r for r in rows if int(r["id"]) == event_id]
    assert matching
    assert matching[0]["source"] is None


def test_cockpit_user_source_via_app_note_command(workspace):
    """The cockpit ``:note`` command tags its events as ``cockpit_user``.

    Exercises the app-side caller of ``data.record_event`` rather than
    the MCP server (which is covered by the existing stdio integration
    test). Two callers, two source tags — distinct provenance per
    origin is the whole point of Phase E2.
    """
    import asyncio

    async def _run() -> dict | None:
        app = CockpitApp()
        async with app.run_test():
            app._execute_command("note phase E smoke")

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_run())
    # Refresh tables before reading (CockpitApp.exit() drops the worker).
    rows = cockpit_data.fetch_new_events(0, limit=100)
    user_rows = [r for r in rows if r.get("source") == "cockpit_user"]
    assert user_rows, "expected the :note command to emit a cockpit_user-tagged row"


def test_memory_mcp_emits_tagged_with_memory_mcp(workspace):
    """Events from memory_mcp tools carry ``source="memory_mcp"``.

    This is the integration test for the cross-module Phase E2 change:
    the helper in ``memory_mcp/tools/_common.py`` hardcodes the source,
    so any tool that emits an event lands with the right tag without
    each call site having to remember.
    """
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")
    rows = cockpit_data.fetch_new_events(0, limit=100)
    memory_rows = [r for r in rows if r.get("source") == "memory_mcp"]
    assert memory_rows, (
        "expected at least one event tagged source=memory_mcp from "
        "memory_mcp.impl.propose_hypothesis"
    )


def test_provenance_label_localizes(workspace):
    from cockpit.details import provenance_label

    assert provenance_label("cockpit_mcp", "en") == "cockpit MCP server"
    assert provenance_label("cockpit_mcp", "zh") == "cockpit MCP 服务"
    # Unknown source → echo (no translation key, fall back to raw).
    assert provenance_label("brand_new_source", "en") == "brand_new_source"
    # Empty / None → localized "unknown".
    assert provenance_label(None, "en") == "unknown"
    assert provenance_label("", "zh") == "未知"


def test_event_detail_includes_source_line(workspace):
    """``event_detail_text`` must surface the source as an "emitted by" row."""
    from cockpit.details import event_detail_text

    row = {
        "id": 42,
        "kind": "note",
        "created_at": "2026-05-08T00:00:00Z",
        "payload": {"text": "smoke"},
        "source": "memory_mcp",
    }
    _title, body = event_detail_text(row, "en")
    assert "emitted by" in body
    assert "memory MCP" in body  # the localized friendly name


# ---------------------------------------------------------------------------
# E3: bookmarks
# ---------------------------------------------------------------------------


def test_bookmarks_field_round_trips_on_disk(tmp_path):
    from cockpit.settings import CockpitSettings, load_settings, save_settings

    settings = CockpitSettings(bookmarks=["hyp_001", "prop_042"])
    target = tmp_path / "cockpit.toml"
    save_settings(settings, target)
    loaded = load_settings(target)
    assert loaded.bookmarks == ["hyp_001", "prop_042"]


def test_bookmarks_field_filters_non_string_garbage(tmp_path):
    """Hand-edited TOML with mixed types should round-trip cleanly."""
    target = tmp_path / "cockpit.toml"
    target.write_text(
        'bookmarks = ["hyp_001", 42, "prop_042"]\n',
        encoding="utf-8",
    )
    from cockpit.settings import load_settings

    loaded = load_settings(target)
    # The int gets dropped; strings survive.
    assert loaded.bookmarks == ["hyp_001", "prop_042"]


@pytest.mark.asyncio
async def test_b_key_toggles_bookmark_on_selection(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")  # ensure a row is selected
        node_id = app.selected_node_id
        assert node_id is not None
        # First b → add.
        await pilot.press("b")
        assert node_id in (app._settings.bookmarks or [])
        # Second b → remove.
        await pilot.press("b")
        assert node_id not in (app._settings.bookmarks or [])


@pytest.mark.asyncio
async def test_capital_b_opens_bookmarks_modal(workspace):
    """``B`` pushes the BookmarksModal onto the screen stack.

    We pre-populate one bookmark so the modal renders the list (rather
    than the empty-state Label) — that way the smoke test exercises the
    interesting branch.
    """
    memory_impl = workspace["memory_mcp.impl"]
    proposed = memory_impl.propose_hypothesis("Tune dropout for ViT")
    app = CockpitApp(settings=None)
    async with app.run_test() as pilot:
        app._settings.bookmarks = [proposed["node_id"]]
        before = len(app.screen_stack)
        await pilot.press("B")
        await pilot.pause()
        assert len(app.screen_stack) > before


@pytest.mark.asyncio
async def test_bookmarks_modal_enter_jumps_to_node(workspace):
    """App-forwarded Enter should submit the highlighted bookmark row."""
    memory_impl = workspace["memory_mcp.impl"]
    first = memory_impl.propose_hypothesis("First candidate")
    second = memory_impl.propose_hypothesis("Second candidate")
    app = CockpitApp(settings=None)
    async with app.run_test() as pilot:
        app._settings.bookmarks = [second["node_id"]]
        app.selected_node_id = first["node_id"]
        before_stack = len(app.screen_stack)
        await pilot.press("B")
        await pilot.pause()
        assert len(app.screen_stack) > before_stack

        await pilot.press("enter")
        await pilot.pause()

        assert len(app.screen_stack) == before_stack
        assert app.selected_node_id == second["node_id"]


def test_tree_pane_renders_bookmark_indicator(workspace):
    """The tree pane prepends ``✦`` to bookmarked rows."""
    from cockpit.data import GraphNode
    from cockpit.panes import HypothesisTreePane

    pane = HypothesisTreePane()
    pane.set_bookmarks(["hyp_a3f1c2"])
    node = GraphNode(
        node_id="hyp_a3f1c2",
        kind="hypothesis",
        text="Tune dropout",
        state="active",
        elo_score=1500.0,
        created_at="2026-05-08T00:00:00Z",
        created_by="test",
        parent_id=None,
    )
    label = pane._label_for(node)
    # The plain-text representation must include the bookmark glyph.
    assert "✦" in str(label)


# ---------------------------------------------------------------------------
# E4: timeline strip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_pane_hidden_by_default(workspace):
    app = CockpitApp()
    async with app.run_test():
        pane = app.timeline_pane
        assert not pane.is_visible


@pytest.mark.asyncio
async def test_timeline_command_toggles_visibility(workspace):
    app = CockpitApp()
    async with app.run_test():
        app._execute_command("timeline")
        assert app.timeline_pane.is_visible
        app._execute_command("timeline")
        assert not app.timeline_pane.is_visible


@pytest.mark.asyncio
async def test_timeline_command_explicit_state_args(workspace):
    """``:timeline on``/``off`` should set state deterministically."""
    app = CockpitApp()
    async with app.run_test():
        app._execute_command("timeline on")
        assert app.timeline_pane.is_visible
        app._execute_command("timeline on")
        # Still visible — idempotent.
        assert app.timeline_pane.is_visible
        app._execute_command("timeline off")
        assert not app.timeline_pane.is_visible


@pytest.mark.asyncio
async def test_timeline_renders_severity_glyphs(workspace):
    """Each event maps to one cell whose glyph encodes its severity tier.

    Runs inside ``app.run_test()`` because :meth:`TimelinePane.set_visible`
    triggers a redraw that calls ``Static.update``, which needs an
    active Textual app context to resolve the console for markup.
    """
    from cockpit.activity import SEVERITY_GLYPH

    app = CockpitApp()
    async with app.run_test():
        pane = app.timeline_pane
        pane.set_visible(True)
        pane.set_events(
            [
                {"id": 1, "kind": "note", "created_at": "x", "payload": {}},
                {"id": 2, "kind": "budget_exceeded", "created_at": "x", "payload": {}},
                {"id": 3, "kind": "failure_added", "created_at": "x", "payload": {}},
            ]
        )
        rendered = str(pane._rendered)
        # The rendered strip must include the severity glyphs for the
        # kinds we inserted.
        assert SEVERITY_GLYPH["critical"] in rendered  # budget_exceeded
        assert SEVERITY_GLYPH["high"] in rendered  # failure_added
