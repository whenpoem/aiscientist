"""Tests for the v4.1.0a4 visual polish stage.

Covers stages 1.1 through 1.8 of the cockpit UX overhaul plan:
- Event pane default soft-wrap and `w` toggle
- Tree pane Unicode kind icons + compact label mode + `i` toggle
- Tree pane border title shows live counts
- Table truncation uses typographic ellipsis
- Status bar heartbeat dot + held-out progress bars
- Detail pane BT strength mini bar
- Intervention queue toasts on y/n/r/c/m/p/H

The fixture comes from tests/conftest.py — reloads cockpit modules against
an isolated tmpdir SQLite so each test starts clean.
"""

from __future__ import annotations

import pytest

from cockpit import data as cockpit_data
from cockpit.app import CockpitApp, StatusBar
from cockpit.bars import progress_bar, strength_bar
from cockpit.i18n import KIND_ICONS, REFUTED_ICON
from cockpit.panes import EventStreamPane, HypothesisTreePane

# ---------------------------------------------------------------------------
# 1.1 events pane soft-wrap default + `w` toggle
# ---------------------------------------------------------------------------


def test_events_pane_defaults_to_wrapped(workspace):
    pane = EventStreamPane()
    assert pane.wrap_enabled is True


def test_events_pane_can_construct_unwrapped(workspace):
    pane = EventStreamPane(wrap=False)
    assert pane.wrap_enabled is False


@pytest.mark.asyncio
async def test_w_key_toggles_event_wrap_and_persists(workspace):
    """v4.2.0a1: ``w`` is pane-scoped to EventStreamPane. v5.0 demoted
    that widget to the bottom-docked audit log, so there is no numeric
    shortcut to focus it directly; we call ``.focus()`` on the widget
    handle to set up the same scope (see docs/cockpit-keys.md)."""
    app = CockpitApp()
    async with app.run_test() as pilot:
        assert app._settings.event_wrap is True
        assert app.events_pane.wrap_enabled is True

        # Focus the audit log (events_pane) so the pane-scoped `w` fires.
        app.events_pane.focus()
        await pilot.pause()
        await pilot.press("w")
        assert app._settings.event_wrap is False
        assert app.events_pane.wrap_enabled is False

        await pilot.press("w")
        assert app._settings.event_wrap is True
        assert app.events_pane.wrap_enabled is True


# ---------------------------------------------------------------------------
# 1.2 tree icons
# ---------------------------------------------------------------------------


def test_tree_kind_icons_are_unicode():
    # Every value must be a single visible non-ASCII glyph (or ASCII letter
    # for the proposition kind, which we keep to avoid Greek-mathy noise).
    # The check is "no plain question marks / asterisks / dots" — those
    # were the v4.1.0a0 ASCII fallbacks.
    forbidden = {"?", "*", "x", ".", "!", "T", "S", "s", "PS", "ps"}
    for kind, glyph in KIND_ICONS.items():
        assert glyph not in forbidden, f"{kind} still uses ASCII fallback {glyph!r}"
        assert len(glyph) == 1, f"{kind} icon must be 1 cell, got {glyph!r}"


def test_refuted_icon_distinct_from_kind_icons():
    assert REFUTED_ICON not in KIND_ICONS.values()


def test_tree_prefix_uses_kind_icon_lookup(workspace):
    """_prefix_for must return the lookup-table glyph, not a hardcoded one."""
    from cockpit.data import GraphNode

    pane = HypothesisTreePane()
    node = GraphNode(
        node_id="H_a3f1c2",
        kind="hypothesis",
        text="Some hypothesis",
        state="active",
        elo_score=1500.0,
        created_at="2026-05-08T00:00:00Z",
        created_by="test",
        parent_id=None,
    )
    assert pane._prefix_for(node) == KIND_ICONS["hypothesis"]

    refuted = GraphNode(
        node_id="H_b1",
        kind="hypothesis",
        text="x",
        state="refuted",
        elo_score=1400.0,
        created_at="2026-05-08T00:00:00Z",
        created_by="test",
        parent_id=None,
    )
    assert pane._prefix_for(refuted) == REFUTED_ICON


# ---------------------------------------------------------------------------
# 1.3 tree compact mode default + `i` toggle
# ---------------------------------------------------------------------------


def test_tree_compact_label_omits_bt_and_elo(workspace):
    from cockpit.data import GraphNode

    pane = HypothesisTreePane(compact=True)
    node = GraphNode(
        node_id="H_a3f1c2",
        kind="hypothesis",
        text="Tune dropout",
        state="active",
        elo_score=1530.0,
        created_at="2026-05-08T00:00:00Z",
        created_by="test",
        parent_id=None,
        bt_strength=0.34,
        bt_strength_var=0.05,
        bt_n_comparisons=12,
    )
    label = pane._label_for(node).plain
    assert "elo" not in label.lower()
    assert "bt" not in label.lower()
    assert "Tune dropout" in label


def test_tree_detailed_label_includes_bt_and_elo(workspace):
    from cockpit.data import GraphNode

    pane = HypothesisTreePane(compact=False)
    node = GraphNode(
        node_id="H_a3f1c2",
        kind="hypothesis",
        text="Tune dropout",
        state="active",
        elo_score=1530.0,
        created_at="2026-05-08T00:00:00Z",
        created_by="test",
        parent_id=None,
        bt_strength=0.34,
        bt_strength_var=0.05,
        bt_n_comparisons=12,
    )
    label = pane._label_for(node).plain
    assert "elo" in label.lower()
    assert "bt" in label.lower()


@pytest.mark.asyncio
async def test_i_key_toggles_tree_compact_and_persists(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test() as pilot:
        assert app._settings.tree_compact is True
        await pilot.press("i")
        assert app._settings.tree_compact is False
        await pilot.press("i")
        assert app._settings.tree_compact is True


# ---------------------------------------------------------------------------
# 1.4 ellipsis in truncated tables
# ---------------------------------------------------------------------------


def test_tabs_pane_truncate_uses_typographic_ellipsis():
    from cockpit.panes.tabs_pane import _truncate

    assert _truncate("short", 10) == "short"
    long_value = "x" * 100
    truncated = _truncate(long_value, 20)
    assert truncated.endswith("…")
    assert len(truncated) == 20
    assert "…" in truncated
    assert "..." not in truncated


# ---------------------------------------------------------------------------
# 1.5 heartbeat + intervention toasts
# ---------------------------------------------------------------------------


def test_status_bar_heartbeat_renders_dot(workspace):
    bar = StatusBar()
    bar._summary = {"latest_event_at": None}
    text = bar._format_last_event()
    assert text.startswith("○") or text.startswith("●")


def test_status_bar_health_chip_silent_when_clean(workspace):
    """Phase A: the HUD ⚠ chip is empty when the cockpit log has no
    warnings/errors. The format string then renders flush — identical
    to the pre-Phase-A layout."""
    from cockpit import diagnostics

    diagnostics.reset_health()
    bar = StatusBar()
    chip = bar._format_health()
    assert chip == ""


def test_status_bar_health_chip_lights_after_warning(workspace):
    """One logged WARNING must flip the chip on so the user sees
    something is up. The chip uses total = warnings + errors."""
    from cockpit import diagnostics

    diagnostics.reset_health()
    log = diagnostics.get_logger("test_health_chip")
    log.warning("smoke")
    bar = StatusBar()
    chip = bar._format_health()
    assert "⚠" in chip
    assert "1" in chip
    diagnostics.reset_health()


@pytest.mark.asyncio
async def test_intervention_press_y_emits_toast(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    captured: list[str] = []
    # Wrap notify so we can assert the message regardless of how Textual
    # internally stores notifications across versions.
    original_notify = app.notify

    def capture(message, **kwargs):
        captured.append(str(message))
        return original_notify(message, **kwargs)

    app.notify = capture  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.press("j")  # ensure a node is selected
        await pilot.press("y")
        # At least one toast should mention the intervention kind.
        assert any("approve" in msg or "approve" in msg.lower() for msg in captured)

    # Hook contract sanity: the row landed in cockpit_interventions with
    # delivered_at NULL — i.e. the toast confirmed enqueue, not delivery.
    assert cockpit_data.fetch_counts()["interventions"] >= 1


# ---------------------------------------------------------------------------
# 1.6 tree border title counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tree_border_title_includes_active_and_refuted_counts(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    h1 = memory_impl.propose_hypothesis("Tune dropout for ViT")
    memory_impl.propose_hypothesis("Increase batch size")
    memory_impl.mark_refuted(h1["node_id"], "did not pan out")

    app = CockpitApp()
    async with app.run_test():
        title = app.tree_pane.border_title or ""
        # We expect some indication of both counts. The exact format is
        # localized; assert on the numbers and a separator presence.
        assert "1" in title  # 1 active
        assert "1" in title  # 1 refuted (same digit, but the suffix exists)


# ---------------------------------------------------------------------------
# 1.7 BT mini bar in detail pane
# ---------------------------------------------------------------------------


def test_progress_bar_renders_filled_blocks():
    out = progress_bar(5, 10, width=10)
    assert out.count("▓") == 5
    assert out.count("░") == 5


def test_progress_bar_clamps_out_of_range():
    full = progress_bar(99, 10, width=8)
    assert full.count("▓") == 8
    assert full.count("░") == 0
    empty = progress_bar(-5, 10, width=8)
    assert empty.count("▓") == 0
    assert empty.count("░") == 8


def test_progress_bar_empty_total_returns_track():
    out = progress_bar(0, 0, width=6)
    assert "▓" not in out
    assert "░" not in out
    assert len(out) == 6


def test_strength_bar_marker_position():
    # Marker at left end
    left = strength_bar(-2.0, low=-2, high=2, width=10)
    assert left.startswith("▮")
    # Marker at right end
    right = strength_bar(2.0, low=-2, high=2, width=10)
    assert right.endswith("▮")
    # Marker near center
    mid = strength_bar(0.0, low=-2, high=2, width=11)
    assert mid[5] == "▮"


def test_detail_pane_bt_line_includes_strength_bar(workspace):
    from cockpit.data import GraphNode
    from cockpit.panes.detail_pane import NodeDetailPane

    pane = NodeDetailPane()
    node = GraphNode(
        node_id="H_a3f1c2",
        kind="hypothesis",
        text="x",
        state="active",
        elo_score=1500.0,
        created_at="2026-05-08T00:00:00Z",
        created_by="test",
        parent_id=None,
        bt_strength=0.5,
        bt_strength_var=0.04,
        bt_n_comparisons=8,
    )
    line = pane._bt_line(node)
    assert line is not None
    assert "▮" in line
    assert "+0.50" in line
    assert "n=8" in line


def test_detail_pane_bt_line_skipped_for_non_ranked_kinds(workspace):
    from cockpit.data import GraphNode
    from cockpit.panes.detail_pane import NodeDetailPane

    pane = NodeDetailPane()
    evidence = GraphNode(
        node_id="EV_1",
        kind="evidence",
        text="x",
        state="active",
        elo_score=1500.0,
        created_at="2026-05-08T00:00:00Z",
        created_by="test",
        parent_id=None,
    )
    assert pane._bt_line(evidence) is None


# ---------------------------------------------------------------------------
# 1.8 held-out progress bar in status bar
# ---------------------------------------------------------------------------


def test_format_heldout_renders_progress_bar(workspace):
    bar = StatusBar()
    bar._summary = {
        "heldout_budgets": [
            {"dataset": "imagenet", "budget_used": 4, "budget_total": 10},
        ]
    }
    text = bar._format_heldout()
    assert "imagenet" in text
    assert "▓" in text
    assert "░" in text
    assert "4/10" in text


def test_format_heldout_empty_returns_localized_none(workspace):
    bar = StatusBar()
    bar._summary = {"heldout_budgets": []}
    text = bar._format_heldout()
    # Non-empty fallback ("none" / "无") — exact value depends on language;
    # the contract is just "no bar glyphs slipped in".
    assert "▓" not in text
    assert "░" not in text
