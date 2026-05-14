"""Tab grouping behavior (v4.2.0a1 / A1).

Three groups, in canonical order:
    cross     → risks, claims, literature
    empirical → failures
    proof     → corpus, diagnostics, lean

Plain ``f`` cycles within the active tab's group. Capital ``N`` jumps
to the first tab of the next group. Both keys wrap.
"""

from __future__ import annotations

import pytest

from cockpit.panes.tabs_pane import (
    TAB_GROUPS,
    TAB_ORDER,
    group_of,
    next_group,
    next_tab_in_group,
    tabs_in_group,
)


def test_tab_order_matches_group_concatenation():
    """TAB_ORDER must be the flat sequence of every group's tabs.

    Pre-grouping callers (drill-in routing, filter rows keys) depend on
    TAB_ORDER staying a flat tuple."""
    expected = tuple(name for _g, names in TAB_GROUPS for name in names)
    assert TAB_ORDER == expected


def test_each_known_tab_resolves_to_exactly_one_group():
    for tab in TAB_ORDER:
        group = group_of(tab)
        assert tab in tabs_in_group(group)


def test_unknown_tab_falls_back_to_first_group():
    """A stale settings file pointing at a removed tab should not crash."""
    fallback = group_of("ghost-tab")
    assert fallback == TAB_GROUPS[0][0]


@pytest.mark.parametrize(
    "current,expected",
    [
        # v5.0 inserted ``focus`` as the first cross-group tab.
        ("focus", "risks"),
        ("risks", "claims"),
        ("claims", "literature"),
        ("literature", "reports"),  # cross group now ends with reports
        ("reports", "focus"),  # wrap within cross (back to focus)
        ("failures", "failures"),  # singleton group stays put
        ("corpus", "diagnostics"),
        ("lean", "corpus"),  # wrap within proof
    ],
)
def test_next_tab_in_group_cycles_within(current, expected):
    assert next_tab_in_group(current) == expected


@pytest.mark.parametrize(
    "current,expected_first",
    [
        # v5.0: cross group now starts with focus.
        ("focus", "failures"),       # cross → empirical
        ("risks", "failures"),       # cross → empirical
        ("claims", "failures"),      # cross → empirical
        ("failures", "corpus"),      # empirical → proof
        ("corpus", "focus"),         # proof → cross (wrap to focus)
        ("lean", "focus"),           # proof → cross (wrap to focus)
    ],
)
def test_next_group_lands_on_first_tab(current, expected_first):
    assert next_group(current) == expected_first


@pytest.mark.asyncio
async def test_f_cycles_within_group_only(workspace):
    """Pressing ``f`` five times starting from Risks should walk
    Cross → Claims → Literature → Reports → Risks (back to start),
    not leak into Empirical or Proof groups."""
    from cockpit.app import CockpitApp

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("4")  # focus tabs pane
        # v5.0: the Focus tab is now the first Cross-group tab.
        assert app.tabs_pane.active == "focus"
        await pilot.press("f")
        assert app.tabs_pane.active == "risks"
        await pilot.press("f")
        assert app.tabs_pane.active == "claims"
        await pilot.press("f")
        assert app.tabs_pane.active == "literature"
        await pilot.press("f")
        assert app.tabs_pane.active == "reports"
        await pilot.press("f")
        assert app.tabs_pane.active == "focus"  # wrapped back to focus


@pytest.mark.asyncio
async def test_capital_n_jumps_to_next_group(workspace):
    """Capital N moves Cross → Empirical → Proof → Cross."""
    from cockpit.app import CockpitApp

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("4")
        # v5.0: Cross group default is now ``focus`` (was ``risks``).
        assert app.tabs_pane.active == "focus"
        await pilot.press("N")
        assert app.tabs_pane.active == "failures"  # Empirical group's first
        await pilot.press("N")
        assert app.tabs_pane.active == "corpus"  # Proof group's first
        await pilot.press("N")
        assert app.tabs_pane.active == "focus"  # wrapped back to Cross


@pytest.mark.asyncio
async def test_group_bar_static_widget_present(workspace):
    """The group strip widget exists at the expected DOM id."""
    from textual.widgets import Static

    from cockpit.app import CockpitApp

    app = CockpitApp()
    async with app.run_test():
        # Reaching the widget by id is the contract; styling lives in
        # cockpit.tcss and Rich markup tags inserted by _refresh_group_bar.
        bar = app.tabs_pane.query_one("#tabs-group-bar", Static)
        assert bar is not None
        assert "tab-group-bar" in bar.classes


@pytest.mark.asyncio
async def test_group_bar_active_group_tracks_cycle(workspace):
    """Cycling tabs updates which group is reported as active.

    The cockpit's group-bar Static refreshes via _refresh_group_bar
    after every cycle_tab / cycle_group; the test asserts the
    underlying state (tabs_pane.active → group_of) tracks the user
    action correctly. The visual styling is owned by cockpit.tcss
    and tested separately by smoke tests rendering the full UI.
    """
    from cockpit.app import CockpitApp

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("4")
        assert group_of(app.tabs_pane.active) == "cross"
        await pilot.press("N")
        assert group_of(app.tabs_pane.active) == "empirical"
        await pilot.press("N")
        assert group_of(app.tabs_pane.active) == "proof"
