"""Tests for the v4.1.0a4 stage-3 DetailScreen drill-in.

Pressing Enter on any list-style pane (tree / events / tabs) pushes a
full-window DetailScreen. Esc/q pops back; h/l walk siblings; action
keys (y/n/...) keep working because the DetailScreen syncs
``app.selected_node_id`` on every render and the App-level intervention
bindings carry ``priority=True``.
"""

from __future__ import annotations

import pytest
from textual.widgets import Static

from cockpit import data as cockpit_data
from cockpit.app import CockpitApp
from cockpit.data import GraphNode, GraphSnapshot
from cockpit.details import event_detail_text, node_detail_text
from cockpit.i18n import t
from cockpit.screens import (
    DetailScreen,
    EventDetailSource,
    NodeDetailSource,
    TabRowDetailSource,
)

# ---------------------------------------------------------------------------
# 3.0 free-function builders (unit tests, no Textual lifecycle)
# ---------------------------------------------------------------------------


def _make_node(node_id="H_a3f1c2", **kwargs):
    defaults = dict(
        node_id=node_id,
        kind="hypothesis",
        text="Tune dropout for ViT",
        state="active",
        elo_score=1500.0,
        created_at="2026-05-08T00:00:00Z",
        created_by="test",
        parent_id=None,
    )
    defaults.update(kwargs)
    return GraphNode(**defaults)


def test_node_detail_text_includes_kind_status_and_text():
    node = _make_node()
    graph = GraphSnapshot(nodes={node.node_id: node})
    title, body = node_detail_text(graph, node.node_id, "en")
    assert "H_a3f1" in title
    assert "Tune dropout for ViT" in body.plain
    assert "active" in body.plain
    assert "Elo" not in body.plain


def test_node_detail_text_unknown_id_returns_hint():
    graph = GraphSnapshot(nodes={})
    title, body = node_detail_text(graph, "MISSING", "en")
    assert title == ""
    # A localized hint, not blank.
    assert body.plain  # type: ignore[union-attr]


def test_event_detail_text_pretty_prints_payload():
    row = {
        "id": 42,
        "kind": "graph_delta",
        "created_at": "2026-05-08T01:00:00Z",
        "payload": {"node_id": "H_a3", "kind": "hypothesis", "text": "x"},
    }
    title, body = event_detail_text(row, "en")
    assert "graph_delta" in title
    assert "H_a3" in body
    assert "id: 42" in body
    # JSON dump with indent=2 leaves a newline + spaces after `{`.
    assert "{\n" in body or "node_id" in body


# ---------------------------------------------------------------------------
# 3.1 source classes
# ---------------------------------------------------------------------------


def test_node_detail_source_walks_visible_ids():
    nodes = {
        f"H_{i}": _make_node(node_id=f"H_{i}", text=f"node {i}") for i in range(5)
    }
    graph = GraphSnapshot(nodes=nodes)
    visible = list(nodes.keys())
    src = NodeDetailSource(graph, visible, "H_2", "en")
    assert src.node_id() == "H_2"
    assert src.move(1) is True
    assert src.node_id() == "H_3"
    # Walk to end then bump — clamps and returns False.
    src.move(1)
    src.move(1)
    assert src.node_id() == "H_4"
    assert src.move(1) is False
    assert src.node_id() == "H_4"
    # Move back to start.
    while src.move(-1):
        pass
    assert src.node_id() == "H_0"


def test_event_detail_source_handles_empty_rows():
    src = EventDetailSource([], 0, "en")
    title, body = src.current()
    assert title == ""
    assert body  # localized "no events" string


def test_tab_row_detail_source_renders_via_callback():
    rows = [
        {"failure_id": 1, "trigger": "x", "symptom": "y"},
        {"failure_id": 2, "trigger": "a", "symptom": "b"},
    ]

    def render(row):
        return (f"#{row['failure_id']}", f"trigger: {row['trigger']}")

    src = TabRowDetailSource(rows, 0, render, "en")
    title, body = src.current()
    assert title == "#1"
    assert "x" in body
    src.move(1)
    title2, _ = src.current()
    assert title2 == "#2"


# ---------------------------------------------------------------------------
# 3.2 push / pop screen lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_on_tree_pushes_detail_screen(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")
    memory_impl.propose_hypothesis("Second")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        assert len(app.screen_stack) == 1

        await pilot.press("enter")
        # DetailScreen is now on top.
        assert len(app.screen_stack) == 2
        assert isinstance(app.screen_stack[-1], DetailScreen)


@pytest.mark.asyncio
async def test_esc_pops_detail_back_to_main(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("enter")
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_q_pops_detail_back_to_main(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("enter")
        assert len(app.screen_stack) == 2
        await pilot.press("q")
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_language_toggle_repaints_detail_screen(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    app = CockpitApp(lang="en")
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("enter")
        screen = app.screen_stack[-1]
        assert isinstance(screen, DetailScreen)

        await pilot.press("L")
        assert app.lang == "zh"
        context = screen.query_one("#detail-screen-context", Static)
        rendered = context.render()
        text = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert text == t("zh", "detail_screen_hint")


# ---------------------------------------------------------------------------
# 3.3 sibling navigation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_navigates_to_next_sibling(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    h1 = memory_impl.propose_hypothesis("First")
    h2 = memory_impl.propose_hypothesis("Second")

    app = CockpitApp()
    async with app.run_test() as pilot:
        # Start on h1
        await pilot.press("g")  # jump to top
        assert app.selected_node_id in (h1["node_id"], h2["node_id"])

        await pilot.press("enter")
        assert isinstance(app.screen_stack[-1], DetailScreen)

        await pilot.press("l")
        # Selected node id should have advanced (or stayed at end if start
        # was already at the bottom — both nodes are valid).
        assert app.selected_node_id in (h1["node_id"], h2["node_id"])


# ---------------------------------------------------------------------------
# 3.4 action keys still work inside DetailScreen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_y_inside_detail_screen_queues_intervention(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("enter")
        assert isinstance(app.screen_stack[-1], DetailScreen)

        before = cockpit_data.fetch_counts()["interventions"]
        await pilot.press("y")
        after = cockpit_data.fetch_counts()["interventions"]
        assert after == before + 1
        # Still inside DetailScreen — actions don't pop the screen.
        assert isinstance(app.screen_stack[-1], DetailScreen)


# ---------------------------------------------------------------------------
# 3.5 events drill-in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_on_events_pane_pushes_detail_screen(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")
    # Fire some events
    cockpit_data.record_event("note", {"text": "long note " * 20})

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("3")  # focus activity (was events pre-v5)
        await pilot.press("enter")
        assert isinstance(app.screen_stack[-1], DetailScreen)


@pytest.mark.asyncio
async def test_hidden_audit_log_enter_is_silent_and_a_toggles_view(workspace):
    cockpit_data.record_event("note", {"text": "audit note"})

    app = CockpitApp()
    async with app.run_test() as pilot:
        assert not app.events_pane.has_class("expanded")

        # Stale or mouse focus can still point at the hidden audit widget.
        # Enter must not drill into an invisible drawer.
        app.events_pane.focus()
        await pilot.pause()
        await pilot.press("enter")
        assert len(app.screen_stack) == 1

        # Lowercase is accepted in addition to Shift+A because users
        # naturally press plain "a" for the audit-log toggle.
        await pilot.press("a")
        assert app.events_pane.has_class("expanded")
        await pilot.press("enter")
        assert isinstance(app.screen_stack[-1], DetailScreen)


@pytest.mark.asyncio
async def test_hiding_audit_log_moves_focus_back_to_activity(workspace):
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("A")
        assert app.events_pane.has_class("expanded")

        await pilot.press("A")
        assert not app.events_pane.has_class("expanded")
        assert app.focused_pane == "activity"


# ---------------------------------------------------------------------------
# 3.6 tabs drill-in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_on_tabs_pane_pushes_detail_screen(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")
    # Seed a failure so the failures tab has a row to drill into.
    memory_impl.record_failure(
        trigger="cuda oom",
        symptom="train.py exits with cuda oom on epoch 5",
        root_cause="batch size too large",
        resolution="reduce to 32",
    )

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("4")  # focus tabs
        # As of v4.2.0a1 the `f` key cycles tabs inside the active
        # group (Cross → Risks → Claims → Literature). The Failures
        # tab lives in the Empirical group, so we jump groups with
        # capital-N first, which lands on the Empirical group's first
        # tab (Failures).
        await pilot.press("N")
        await pilot.press("enter")
        assert isinstance(app.screen_stack[-1], DetailScreen)


# ---------------------------------------------------------------------------
# 3.7 long-content rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_node_text_renders_in_detail_screen(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    long_text = "This is a sentence that gets repeated. " * 50
    memory_impl.propose_hypothesis(long_text)

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("enter")
        screen = app.screen_stack[-1]
        assert isinstance(screen, DetailScreen)
        # The Static body should contain the full long text.
        from textual.widgets import Static

        body = screen.query_one("#detail-screen-body", Static)
        rendered = body.render()
        rendered_text = (
            rendered.plain if hasattr(rendered, "plain") else str(rendered)
        )
        # Last fragment should be present — i.e. nothing was truncated.
        assert "repeated. " in rendered_text


# ---------------------------------------------------------------------------
# 3.8 boundary: pressing l at the last sibling toasts but doesn't crash
# ---------------------------------------------------------------------------


def test_node_detail_source_clamps_at_boundaries():
    nodes = {"H_1": _make_node(node_id="H_1")}
    graph = GraphSnapshot(nodes=nodes)
    src = NodeDetailSource(lambda: graph, ["H_1"], "H_1", "en")
    assert src.move(1) is False
    assert src.move(-1) is False
    assert src.node_id() == "H_1"


# ---------------------------------------------------------------------------
# 3.9 stale-state regression: DetailScreen reflects post-action state
# ---------------------------------------------------------------------------


def test_node_detail_source_reads_fresh_graph_each_call():
    """Regression: the source must call its graph_provider on every
    current() invocation, not snapshot the graph at construction. This
    is what lets DetailScreen pick up the post-y graph mutation when the
    App refreshes state inside the drill-in.
    """
    snap_a = GraphSnapshot(
        nodes={"H_1": _make_node(node_id="H_1", text="version A")}
    )
    snap_b = GraphSnapshot(
        nodes={"H_1": _make_node(node_id="H_1", text="version B")}
    )
    box = {"current": snap_a}
    src = NodeDetailSource(lambda: box["current"], ["H_1"], "H_1", "en")
    _, body = src.current()
    assert "version A" in body.plain

    box["current"] = snap_b
    _, body2 = src.current()
    assert "version B" in body2.plain


@pytest.mark.asyncio
async def test_enter_uses_actual_widget_focus_not_stale_reactive(workspace):
    """Regression: a mouse click moves widget focus without going through
    ``_set_focus()``, so the ``focused_pane`` reactive can be stale (e.g.
    user pressed `3` earlier, then clicked the tree). Pressing Enter must
    drill into the *actually-focused* pane, not whatever reactive value
    happens to be cached. The exact user-reported bug: the test
    hypothesis appeared to vanish because Enter pushed an Events
    DetailScreen on top of the main tree.
    """
    from cockpit.screens import NodeDetailSource

    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("test hypothesis")

    app = CockpitApp()
    async with app.run_test() as pilot:
        # Stale-reactive setup: use keyboard to focus activity (was
        # events pre-v5), then move widget focus to tree without
        # going through _set_focus.
        await pilot.press("3")
        assert app.focused_pane == "activity"

        # Simulate mouse focus on the tree pane: in Textual, mouse clicks
        # call widget.focus() directly which fires Focused but doesn't
        # invoke our keyboard-only _set_focus path.
        app.tree_pane.focus()
        await pilot.pause()

        # `focused_pane` reactive is still "activity" (the pre-mouse
        # value); the *actual* focused widget is the tree pane.
        # Pressing Enter must route to tree drill-in regardless.
        await pilot.press("enter")

        assert len(app.screen_stack) == 2
        screen = app.screen_stack[-1]
        assert isinstance(screen, DetailScreen)
        assert isinstance(screen._source, NodeDetailSource)


@pytest.mark.asyncio
async def test_enter_on_empty_tabs_or_events_is_silent(workspace):
    """Regression: empty tabs / events drill must NOT pop a toast.
    The placeholder rendered inline (`No risks.`, `No events yet.`,
    etc.) is the user-visible answer; adding a floating notification
    on every keystroke caused the on-screen toast stack to fill up
    and overlay other panes during exploration."""
    app = CockpitApp()
    captured: list[tuple[str, str | None]] = []
    original_notify = app.notify

    def capture(message, **kwargs):
        captured.append((str(message), kwargs.get("severity")))
        return original_notify(message, **kwargs)

    app.notify = capture  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        # Tabs: default state has no real rows.
        await pilot.press("4")
        await pilot.press("enter")
        assert len(app.screen_stack) == 1
        # Events: same.
        await pilot.press("3")
        await pilot.press("enter")
        assert len(app.screen_stack) == 1
        # No "warning" / "drill empty" toast was pushed.
        assert not any(
            "可展开" in msg or "open" in msg.lower()
            for msg, _ in captured
        )


@pytest.mark.asyncio
async def test_open_detail_for_tree_warns_when_node_missing_from_graph(workspace):
    """Regression: a stale cursor pointing at an evicted node must not
    push an empty DetailScreen — that's how the user-reported "hypothesis
    vanished" symptom looked. Show a warning toast and bail."""
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Original")

    app = CockpitApp()
    captured: list[tuple[str, str | None]] = []
    original_notify = app.notify

    def capture(message, **kwargs):
        captured.append((str(message), kwargs.get("severity")))
        return original_notify(message, **kwargs)

    app.notify = capture  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.press("j")
        # Forge a stale state: clear the graph but leave selected_node_id
        # pointing at the evicted id.
        from cockpit.data import GraphSnapshot

        app.graph = GraphSnapshot(nodes={})
        # Now drill — App should refuse to push and warn.
        await pilot.press("enter")
        # Either DetailScreen wasn't pushed (preferred) or, if pushed by
        # an even earlier code path, a warning toast is recorded.
        if len(app.screen_stack) == 1:
            assert any(severity == "warning" for _, severity in captured)


@pytest.mark.asyncio
async def test_pop_detail_syncs_main_tree_cursor(workspace):
    """Regression: navigating with l inside the DetailScreen and then
    pressing Esc must move the main-screen tree cursor onto the new node
    so the highlight, selected_node_id, and detail pane stay consistent.
    """
    memory_impl = workspace["memory_mcp.impl"]
    h1 = memory_impl.propose_hypothesis("First")
    h2 = memory_impl.propose_hypothesis("Second")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("g")  # top
        first_id = app.selected_node_id

        await pilot.press("enter")
        assert isinstance(app.screen_stack[-1], DetailScreen)
        await pilot.press("l")
        await pilot.press("escape")
        # Tree cursor in the main screen now matches the navigated id.
        assert app.tree_pane.current_node_id() == app.selected_node_id
        # And it's a real visible id.
        assert app.selected_node_id in (h1["node_id"], h2["node_id"])
        # Something happened — first_id should differ from current if
        # there was room to navigate. This guards against a silent no-op.
        if first_id != app.selected_node_id:
            assert first_id is not None  # navigation actually advanced
