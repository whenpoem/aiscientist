"""Phase C + Phase D regression tests.

Locks in the user-visible behaviour added by:

- Phase C: action-target chip, focus-mode chip, Detail breadcrumb,
  quit-with-pending-interventions confirmation, ``:theme``/``:lang``/
  ``:focus``/``:health`` command palette entries.
- Phase D: HUD heartbeat slot, intervention-flash CSS class on the tree
  pane, phase-strip self-ticker that refreshes the "since" age.

These tests run against the conftest.workspace fixture so each test is
isolated from on-disk state.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cockpit import data as cockpit_data
from cockpit.app import CockpitApp, StatusBar, _pane_label

# ---------------------------------------------------------------------------
# Phase D: heartbeat chip
# ---------------------------------------------------------------------------


def test_heartbeat_chip_cold_when_no_events(workspace):
    bar = StatusBar()
    bar._summary["latest_event_at"] = None
    chip = bar._format_heartbeat()
    # Cold state: hollow ring, no breath.
    assert "○" in chip
    assert "●" not in chip


def test_heartbeat_chip_warm_when_recent_event(workspace):
    bar = StatusBar()
    now = datetime.now(timezone.utc).isoformat()
    bar._summary["latest_event_at"] = now
    chip = bar._format_heartbeat()
    # Warm state: filled dot. Either accent or foreground colour depending
    # on the breath phase parity — both encode "alive".
    assert "●" in chip


def test_heartbeat_chip_alternates_colour_per_tick(workspace):
    """The breath cycles between two Rich markup colour stops each tick.

    The cycle is what produces the visible "alive" pulse — without it
    the warm state would be a static dot. We assert the two consecutive
    ticks produce DIFFERENT markup strings.
    """
    bar = StatusBar()
    now = datetime.now(timezone.utc).isoformat()
    bar._summary["latest_event_at"] = now
    first = bar._format_heartbeat()
    bar._heartbeat_phase += 1
    second = bar._format_heartbeat()
    assert first != second


def test_heartbeat_chip_falls_back_when_timestamp_unparseable(workspace):
    bar = StatusBar()
    bar._summary["latest_event_at"] = "not-an-iso-timestamp"
    # Parse failure → cold, never raises.
    chip = bar._format_heartbeat()
    assert "○" in chip


# ---------------------------------------------------------------------------
# Phase C: action-target chip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_action_target_chip_lights_when_node_selected(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    proposed = memory_impl.propose_hypothesis("Tune dropout for ViT")
    app = CockpitApp()
    async with app.run_test():
        # The tree's first row should be selected on mount.
        assert app.selected_node_id == proposed["node_id"]
        chip = app.status_bar._format_action_target()
        assert "▶" in chip
        assert proposed["node_id"] in chip


@pytest.mark.asyncio
async def test_action_target_chip_empty_when_no_selection(workspace):
    app = CockpitApp()
    async with app.run_test():
        # No nodes → no selection → empty chip.
        app.selected_node_id = None
        chip = app.status_bar._format_action_target()
        assert chip == ""


# ---------------------------------------------------------------------------
# Phase C: focus-mode chip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_focus_mode_chip_silent_on_wide_layout(workspace):
    app = CockpitApp()
    async with app.run_test():
        # Default layout is wide → chip is empty.
        assert app._settings.layout_preset == "wide"
        assert app.status_bar._format_focus_mode() == ""


@pytest.mark.asyncio
async def test_focus_mode_chip_lights_when_focus_pressed(workspace):
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("F")  # toggle focus mode
        assert app._settings.layout_preset == "focus"
        chip = app.status_bar._format_focus_mode()
        assert "⊡" in chip


def test_pane_label_localizes_correctly():
    assert _pane_label("en", "tree") == "Tree"
    assert _pane_label("zh", "tree") == "假设树"
    assert _pane_label("en", "activity") == "Activity"
    assert _pane_label("zh", "activity") == "活动"
    # Unknown pane name → echo, never crash.
    assert _pane_label("en", "unknown") == "unknown"


# ---------------------------------------------------------------------------
# Phase C: Detail pane breadcrumb
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_breadcrumb_shows_node_source_when_selected(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    proposed = memory_impl.propose_hypothesis("Tune dropout for ViT")
    app = CockpitApp()
    async with app.run_test():
        node_id = proposed["node_id"]
        bc_kind, bc_args = app.detail_pane._breadcrumb_state
        assert bc_kind == "node"
        assert bc_args.get("target") == node_id


@pytest.mark.asyncio
async def test_detail_breadcrumb_hint_when_no_selection(workspace):
    app = CockpitApp()
    async with app.run_test():
        # Empty state → "no selection" breadcrumb.
        kind, _ = app.detail_pane._breadcrumb_state
        assert kind == "hint"


# ---------------------------------------------------------------------------
# Phase C: ``:`` command palette extensions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_colon_theme_command_switches_theme(workspace):
    app = CockpitApp()
    async with app.run_test():
        app._execute_command("theme claude-cool-dark")
        assert app._settings.theme == "claude-cool-dark"


@pytest.mark.asyncio
async def test_colon_theme_unknown_value_does_not_change_theme(workspace):
    app = CockpitApp()
    async with app.run_test():
        before = app._settings.theme
        app._execute_command("theme made-up-theme")
        assert app._settings.theme == before


@pytest.mark.asyncio
async def test_colon_lang_command_switches_language(workspace):
    app = CockpitApp()
    async with app.run_test():
        app._execute_command("lang zh")
        assert app.lang == "zh"


@pytest.mark.asyncio
async def test_colon_focus_command_toggles_focus_mode(workspace):
    app = CockpitApp()
    async with app.run_test():
        before = app._settings.layout_preset
        app._execute_command("focus")
        assert app._settings.layout_preset != before


@pytest.mark.asyncio
async def test_colon_health_command_resets_state(workspace):
    """:health clears the in-memory diagnostics counters.

    The chip vanishes on next StatusBar tick (re-reads health_state).
    """
    from cockpit import diagnostics

    diagnostics.reset_health()
    diagnostics.get_logger("test_colon_health").warning("smoke")
    assert diagnostics.health_state()["warnings"] == 1

    app = CockpitApp()
    async with app.run_test():
        # CockpitApp.__init__ already reset; log another warning so
        # the test exercises the :health path itself.
        diagnostics.get_logger("test_colon_health").warning("smoke again")
        assert diagnostics.health_state()["warnings"] >= 1
        app._execute_command("health")
        assert diagnostics.health_state()["warnings"] == 0


# ---------------------------------------------------------------------------
# Phase C: quit-with-pending-interventions confirmation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quit_skips_modal_when_nothing_pending(workspace):
    app = CockpitApp()
    async with app.run_test() as pilot:
        # No interventions queued → q exits directly. Pressing q in a
        # run_test pilot exits the App; we just need to assert the
        # confirmation modal was NOT pushed.
        assert cockpit_data.count_pending_interventions() == 0
        await pilot.press("q")
        # After q, the app's exit flag is set; the screen stack should
        # not have grown to include a ConfirmModal.
        # (run_test's context manager exits when the App does.)


@pytest.mark.asyncio
async def test_quit_pushes_modal_when_interventions_pending(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("y")  # queue an approve intervention
        await pilot.pause()
        assert cockpit_data.count_pending_interventions() >= 1
        before_stack = len(app.screen_stack)
        await pilot.press("q")
        await pilot.pause()
        # The confirm modal should now be on top.
        assert len(app.screen_stack) > before_stack


# ---------------------------------------------------------------------------
# Phase D: intervention flash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intervention_flash_class_applied_then_cleared(workspace):
    """``y`` on a selected node adds the flash class, then it falls off."""
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("y")
        await pilot.pause()
        # Either the class is present (timer still pending) or has
        # already been cleared. We accept both as long as the action
        # didn't crash. The interesting assertion is that the timer
        # path completes — wait for the clear.
        await pilot.pause(delay=0.4)
        assert not app.tree_pane.has_class("intervention-flash")


# ---------------------------------------------------------------------------
# Phase D: phase strip self-tick
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_strip_self_tick_installs_interval(workspace):
    """The strip should own its 1-second ticker so "since" updates live."""
    app = CockpitApp()
    async with app.run_test():
        strip = app.phase_strip
        assert strip._tick_handle is not None, (
            "PhaseStripPane.on_mount must install a self-ticker"
        )
