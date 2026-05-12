"""Key-binding scope behavior (v4.2.0a1 / A3).

The cockpit's bindings split into four scopes:

- **Global** (priority): `L T F H R N u < > q Esc Ctrl+L Ctrl+P`
- **Selection actions**: `y n r c m p`
- **Movement**: `j k h l g G 1-4 Tab Enter f`
- **Pane-scoped**: `w` (events pane only), `i` (tree pane only)

These tests cover the pane-scoped split since that's the v4.2.0a1
behavior change. The other three scopes were stable through v4.1 and
are exercised by existing tests in this directory.
"""

from __future__ import annotations

import pytest

from cockpit.app import CockpitApp


@pytest.mark.asyncio
async def test_w_fires_in_events_pane(workspace):
    """Pressing `w` while the events pane has focus toggles wrap."""
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("3")  # focus events
        before = app.events_pane.wrap_enabled
        await pilot.press("w")
        assert app.events_pane.wrap_enabled is (not before)


@pytest.mark.asyncio
async def test_w_does_not_fire_from_tree_pane(workspace):
    """Pressing `w` while the tree pane has focus is a no-op now.

    v4.1 fired the wrap toggle regardless of focus through an
    App-level priority binding. v4.2 scopes `w` to the events pane.
    """
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("1")  # focus tree
        before = app.events_pane.wrap_enabled
        await pilot.press("w")
        assert app.events_pane.wrap_enabled is before


@pytest.mark.asyncio
async def test_i_fires_in_tree_pane(workspace):
    """Pressing `i` while the tree pane has focus toggles compact mode."""
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("1")  # focus tree
        before = app.tree_pane._compact
        await pilot.press("i")
        assert app.tree_pane._compact is (not before)


@pytest.mark.asyncio
async def test_i_does_not_fire_from_events_pane(workspace):
    """Pressing `i` while the events pane has focus is a no-op."""
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("3")  # focus events
        before = app.tree_pane._compact
        await pilot.press("i")
        assert app.tree_pane._compact is before


@pytest.mark.asyncio
async def test_global_priority_letters_still_fire_from_anywhere(workspace):
    """Capital `L` (language toggle) is global priority — it works
    regardless of which pane has focus."""
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("1")  # focus tree
        lang_before = app.lang
        await pilot.press("L")
        assert app.lang != lang_before

        await pilot.press("4")  # focus tabs
        lang_after_tabs = app.lang
        await pilot.press("L")
        assert app.lang != lang_after_tabs
