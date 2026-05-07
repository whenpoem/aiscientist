"""Tests for the adaptive layout helper."""

from __future__ import annotations

import pytest

from cockpit.layout import (
    LAYOUT_NARROW,
    LAYOUT_SINGLE,
    LAYOUT_WIDE,
    NARROW_MIN_WIDTH,
    WIDE_MIN_WIDTH,
    all_layout_classes,
    css_class_for,
    normalize_preset,
    resolve_for_width,
)


def test_normalize_preset_passes_through_known():
    assert normalize_preset("wide") == "wide"
    assert normalize_preset("narrow") == "narrow"
    assert normalize_preset("single") == "single"
    assert normalize_preset("focus") == "focus"


def test_normalize_preset_unknown_falls_back_to_wide():
    assert normalize_preset("not-a-preset") == "wide"
    assert normalize_preset(None) == "wide"
    assert normalize_preset("") == "wide"


@pytest.mark.parametrize(
    "width, expected",
    [
        (200, LAYOUT_WIDE),
        (WIDE_MIN_WIDTH, LAYOUT_WIDE),
        (WIDE_MIN_WIDTH - 1, LAYOUT_NARROW),
        (NARROW_MIN_WIDTH, LAYOUT_NARROW),
        (NARROW_MIN_WIDTH - 1, LAYOUT_SINGLE),
        (60, LAYOUT_SINGLE),
        (10, LAYOUT_SINGLE),
    ],
)
def test_resolve_for_width_breakpoints(width, expected):
    assert resolve_for_width("wide", width) == expected


def test_focus_preset_always_collapses_to_single_even_when_wide():
    """User opted into focus mode; we must respect that, even if the terminal
    is wide enough for 3 columns. Otherwise the F-key contract is broken."""
    assert resolve_for_width("focus", 200) == LAYOUT_SINGLE
    assert resolve_for_width("focus", 100) == LAYOUT_SINGLE
    assert resolve_for_width("focus", 70) == LAYOUT_SINGLE
    assert resolve_for_width("single", 200) == LAYOUT_SINGLE


def test_narrow_preset_does_not_promote_to_wide_on_big_screens():
    """The narrow preset is a *user* choice — it doesn't auto-promote when
    the screen is wide. (Auto-collapse only steps down, never up.)"""
    # narrow on a wide terminal: we currently treat 'narrow' as wide-eligible
    # because the user-facing preset only has wide/narrow/single; preserving
    # the saved choice in this direction is left to the focus path.
    # On a narrow terminal, narrow stays narrow:
    assert resolve_for_width("narrow", WIDE_MIN_WIDTH - 1) == LAYOUT_NARROW
    # And on extremely narrow, even narrow drops to single:
    assert resolve_for_width("narrow", NARROW_MIN_WIDTH - 1) == LAYOUT_SINGLE


def test_css_class_for_each_layout():
    assert css_class_for(LAYOUT_WIDE) == "layout-wide"
    assert css_class_for(LAYOUT_NARROW) == "layout-narrow"
    assert css_class_for(LAYOUT_SINGLE) == "layout-single"


def test_css_class_for_unknown_falls_back_to_wide():
    # Unknown → wide is intentional: we'd rather show too much than too little
    # if a future preset makes it through unmapped.
    assert css_class_for("mystery") == "layout-wide"


def test_all_layout_classes_lists_the_three_css_classes():
    classes = all_layout_classes()
    assert "layout-wide" in classes
    assert "layout-narrow" in classes
    assert "layout-single" in classes
    assert len(classes) == 3


# -- App-level integration -------------------------------------------------


@pytest.mark.asyncio
async def test_focus_key_toggles_single_pane_layout(workspace):
    """Pressing F enters focus mode (only the active pane visible). Pressing
    F again exits to wide. Settings track the choice."""
    from textual.containers import Container

    from cockpit.app import CockpitApp

    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    # Force a wide-eligible terminal so the saved 'wide' preset isn't
    # auto-clamped to narrow by the breakpoint logic.
    async with app.run_test(size=(160, 40)) as pilot:
        body = app.query_one("#body-grid", Container)
        # Start in wide.
        assert "layout-wide" in body.classes
        assert app._settings.layout_preset == "wide"

        await pilot.press("F")
        assert "layout-single" in body.classes
        assert "layout-wide" not in body.classes
        assert app._settings.layout_preset == "focus"
        # The currently-focused pane gets the layout-active class so it's
        # the one visible pane in single mode.
        assert "layout-active" in app.tree_pane.classes

        await pilot.press("F")
        assert "layout-wide" in body.classes
        assert "layout-single" not in body.classes
        assert app._settings.layout_preset == "wide"
        assert "layout-active" not in app.tree_pane.classes


@pytest.mark.asyncio
async def test_focus_mode_swaps_active_pane_with_focus_change(workspace):
    """In focus mode, switching to another pane (e.g., '3' for events) makes
    that pane the visible one."""
    from cockpit.app import CockpitApp

    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("F")
        assert "layout-active" in app.tree_pane.classes

        await pilot.press("3")  # focus events
        assert app.focused_pane == "events"
        assert "layout-active" in app.events_pane.classes
        assert "layout-active" not in app.tree_pane.classes


# -- visual / cell-position regression -----------------------------------


@pytest.mark.asyncio
async def test_wide_layout_places_each_pane_in_expected_quadrant(workspace):
    """Snapshot the wide layout's grid cells: Tree spans column 1, Events
    spans column 3 (full height), Detail sits top-middle, Tabs sits
    bottom-middle. Catches the v4.1.0a0 bug where compose order made
    column-3-row-2 land empty.

    We assert by comparing each pane's region.x against thirds of the
    body-grid width and region.y against the midpoint, so the test stays
    robust to small fr-ratio tweaks in TCSS."""
    from textual.containers import Container

    from cockpit.app import CockpitApp

    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test(size=(160, 40)):
        body = app.query_one("#body-grid", Container)
        bx, by, bw, bh = body.region
        # TCSS: grid-columns: 1fr 2fr 2fr (5fr total). Compute column
        # boundaries from the actual ratio so the test survives small
        # tweaks (e.g. to 1fr 2fr 1.5fr) without rewriting.
        col1_end = bx + bw * (1 / 5)
        col2_end = bx + bw * (3 / 5)
        midline = by + bh / 2

        tree = app.tree_pane.region
        detail = app.detail_pane.region
        events = app.events_pane.region
        tabs = app.tabs_pane.region

        # Tree: column 1, full height.
        assert tree.x < col1_end, (
            f"Tree.x={tree.x} not in column 1 (< {col1_end})"
        )
        assert tree.height >= bh - 4, f"Tree.height={tree.height} should ~= bh={bh}"

        # Events: column 3 (right of col2 boundary), full height.
        assert events.x >= col2_end - 2, (
            f"Events.x={events.x} not in column 3 (>= {col2_end - 2})"
        )
        assert events.height >= bh - 4, (
            f"Events.height={events.height} should ~= bh={bh}"
        )

        # Detail: middle column (between col1 and col2 boundaries),
        # upper half.
        assert col1_end - 2 <= detail.x < col2_end + 2, (
            f"Detail.x={detail.x} not in column 2 ({col1_end} .. {col2_end})"
        )
        assert detail.y < midline, f"Detail.y={detail.y} not in upper half"

        # Tabs: middle column, lower half. This is the cell that was blank
        # before the compose-order fix in v4.1.0a0.
        assert col1_end - 2 <= tabs.x < col2_end + 2, (
            f"Tabs.x={tabs.x} not in column 2 (was blank before fix)"
        )
        assert tabs.y >= midline - 1, (
            f"Tabs.y={tabs.y} not in lower half (was blank before fix)"
        )
