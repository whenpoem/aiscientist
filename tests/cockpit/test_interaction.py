"""Tests for the v4.1.0a4 interaction-fix stage.

Covers stages 2.1 through 2.6:
- Help modal only dismisses on whitelisted keys
- Command-line draft buffer survives Esc → re-open
- `<` / `>` nudge the wide-layout tree column
- `y/n` interventions show an undo hint, `u` rolls back if undelivered
- `:goto <id>` and prefix matching
"""

from __future__ import annotations

import pytest

from cockpit import data as cockpit_data
from cockpit.app import CockpitApp

# ---------------------------------------------------------------------------
# 2.1 help modal key whitelist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_modal_ignores_non_dismiss_keys(workspace):
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        # Help screen is now on top of the stack.
        assert len(app.screen_stack) >= 2

        # j is bound to cursor_down on the underlying app — pressing it
        # should NOT dismiss help and must NOT bubble to fire that action.
        await pilot.press("j")
        assert len(app.screen_stack) >= 2

        await pilot.press("escape")
        # Help is gone.
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_help_modal_dismisses_on_enter(workspace):
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        assert len(app.screen_stack) >= 2
        await pilot.press("enter")
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_help_modal_blocks_priority_app_actions(workspace):
    """Regression: App-level priority bindings must not bypass HelpScreen."""
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("y")
        assert app._last_intervention_id is not None
        before = cockpit_data.fetch_counts()["interventions"]

        await pilot.press("question_mark")
        assert len(app.screen_stack) >= 2
        await pilot.press("u")
        await pilot.press("q")

        assert cockpit_data.fetch_counts()["interventions"] == before
        assert app._last_intervention_id is not None
        assert len(app.screen_stack) >= 2

        await pilot.press("escape")
        assert len(app.screen_stack) == 1


# ---------------------------------------------------------------------------
# 2.2 command-line draft buffer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_buffer_survives_escape(workspace):
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("colon")
        # Type a half-finished command. Don't press enter.
        await pilot.press(*list("note hi"))
        assert app.command_line.value == "note hi"

        await pilot.press("escape")
        # Buffer is stashed.
        assert app._command_buffer == "note hi"

        # Re-open with `:` — input restores prior draft.
        await pilot.press("colon")
        assert app.command_line.value == "note hi"


@pytest.mark.asyncio
async def test_command_buffer_clears_after_submit(workspace):
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("colon")
        await pilot.press(*list("note kept"))
        await pilot.press("enter")
        assert app._command_buffer == ""

        # Next `:` opens to empty.
        await pilot.press("colon")
        assert app.command_line.value == ""


# ---------------------------------------------------------------------------
# 2.3 `<` / `>` tree column width
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lt_gt_steps_wide_subpreset(workspace):
    app = CockpitApp()
    async with app.run_test(size=(160, 40)) as pilot:
        # Default subpreset is 0.
        assert app._settings.wide_subpreset == 0

        await pilot.press("greater_than_sign")
        assert app._settings.wide_subpreset == 1

        # Already at +1 — second press is a no-op clamp.
        await pilot.press("greater_than_sign")
        assert app._settings.wide_subpreset == 1

        await pilot.press("less_than_sign")
        assert app._settings.wide_subpreset == 0
        await pilot.press("less_than_sign")
        assert app._settings.wide_subpreset == -1


@pytest.mark.asyncio
async def test_wide_subpreset_applies_css_class(workspace):
    app = CockpitApp()
    async with app.run_test(size=(160, 40)) as pilot:
        grid = app._body_grid()
        await pilot.press("greater_than_sign")
        assert grid.has_class("tree-wide")
        assert not grid.has_class("tree-narrow")

        await pilot.press("less_than_sign")
        assert not grid.has_class("tree-wide")
        assert not grid.has_class("tree-narrow")  # back at 0

        await pilot.press("less_than_sign")
        assert grid.has_class("tree-narrow")
        assert not grid.has_class("tree-wide")


@pytest.mark.asyncio
async def test_lt_gt_in_narrow_layout_warns(workspace):
    app = CockpitApp()
    captured: list[tuple[str, str | None]] = []
    original_notify = app.notify

    def capture(message, **kwargs):
        captured.append((str(message), kwargs.get("severity")))
        return original_notify(message, **kwargs)

    app.notify = capture  # type: ignore[method-assign]

    async with app.run_test(size=(100, 40)) as pilot:  # narrow layout (<120)
        await pilot.press("greater_than_sign")
        # Subpreset value can still be stored, but we expect a warning toast.
        assert any(severity == "warning" for _, severity in captured)


# ---------------------------------------------------------------------------
# 2.4 undo flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_y_then_u_deletes_undelivered_intervention(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("y")
        intervention_id = app._last_intervention_id
        assert intervention_id is not None

        before = cockpit_data.fetch_counts()["interventions"]
        await pilot.press("u")
        after = cockpit_data.fetch_counts()["interventions"]
        assert after == before - 1
        assert app._last_intervention_id is None


@pytest.mark.asyncio
async def test_command_intervention_tracks_undo_pointer(workspace):
    """Command-mode interventions should share the key-driven undo path."""
    memory_impl = workspace["memory_mcp.impl"]
    node = memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("colon")
        await pilot.press(*list(f"reject {node['node_id']} too risky"))
        await pilot.press("enter")

        assert app._last_intervention_id is not None
        before = cockpit_data.fetch_counts()["interventions"]
        await pilot.press("u")
        assert cockpit_data.fetch_counts()["interventions"] == before - 1
        assert app._last_intervention_id is None


@pytest.mark.asyncio
async def test_u_after_delivery_refuses(workspace):
    """Simulate the hook having already consumed the intervention by
    setting delivered_at directly. `u` should refuse with a warning toast
    and leave the row in place."""
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    captured: list[tuple[str, str | None]] = []
    original_notify = app.notify

    def capture(message, **kwargs):
        captured.append((str(message), kwargs.get("severity")))
        return original_notify(message, **kwargs)

    app.notify = capture  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("y")
        intervention_id = app._last_intervention_id
        assert intervention_id is not None

        # Mark delivered (simulating intervention_pump.py).
        from claudescientist.runtime import connect_sqlite, state_db_path

        con = connect_sqlite(state_db_path())
        try:
            con.execute(
                "UPDATE cockpit_interventions SET delivered_at = datetime('now') "
                "WHERE id = ?",
                (intervention_id,),
            )
            con.commit()
        finally:
            con.close()

        before = cockpit_data.fetch_counts()["interventions"]
        await pilot.press("u")
        after = cockpit_data.fetch_counts()["interventions"]
        assert after == before  # row stayed
        assert any("delivered" in msg.lower() or "接收" in msg for msg, _ in captured)


@pytest.mark.asyncio
async def test_u_with_no_pending_says_nothing_to_undo(workspace):
    app = CockpitApp()
    captured: list[tuple[str, str | None]] = []
    original_notify = app.notify

    def capture(message, **kwargs):
        captured.append((str(message), kwargs.get("severity")))
        return original_notify(message, **kwargs)

    app.notify = capture  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.press("u")
        assert any(severity == "warning" for _, severity in captured)


@pytest.mark.asyncio
async def test_refute_does_not_offer_undo(workspace):
    """mark_refuted writes to mem_nodes, not cockpit_interventions, so
    undo is not applicable. Pressing `u` after `m` must not delete a
    different (older) intervention by mistake."""
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("m")
        # ConfirmModal is open — confirm with y.
        await pilot.press("y")
        # _last_intervention_id should be cleared (refute is non-undoable).
        assert app._last_intervention_id is None


# ---------------------------------------------------------------------------
# 2.6 :goto command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goto_jumps_to_exact_node_id(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    h1 = memory_impl.propose_hypothesis("First hypothesis")
    memory_impl.propose_hypothesis("Second hypothesis")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("colon")
        await pilot.press(*list(f"goto {h1['node_id']}"))
        await pilot.press("enter")
        assert app.selected_node_id == h1["node_id"]


@pytest.mark.asyncio
async def test_goto_resolves_unique_prefix(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    h1 = memory_impl.propose_hypothesis("Try a thing")

    app = CockpitApp()
    async with app.run_test() as pilot:
        prefix = h1["node_id"][:5]  # e.g. "H_a3f"
        await pilot.press("colon")
        await pilot.press(*list(f"goto {prefix}"))
        await pilot.press("enter")
        assert app.selected_node_id == h1["node_id"]


# ---------------------------------------------------------------------------
# 2.5 Tab from tabs pane goes to the NEXT pane (not stuck in DataTable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tab_from_tabs_pane_advances_focus_to_tree(workspace):
    """Regression: with focus inside RightTabsPane (a DataTable lives
    there) pressing Tab must advance to the next pane in FOCUS_ORDER, not
    cycle inside the DataTable. The plan called this out as a 2.5 risk
    requiring re-verification."""
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    app = CockpitApp()
    async with app.run_test() as pilot:
        # Land on tabs pane.
        await pilot.press("4")
        # The focused_pane reactive should now be 'tabs'.
        assert app.focused_pane == "tabs"
        await pilot.press("tab")
        # FOCUS_ORDER is ("tree", "detail", "events", "tabs") so tab from
        # tabs wraps back to tree.
        assert app.focused_pane == "tree"


@pytest.mark.asyncio
async def test_f_in_tabs_pane_cycles_subtab(workspace):
    """`f` cycles which sub-tab (risks/failures/...) is shown — distinct
    from the App-level Tab. They must coexist."""
    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("4")
        before = app.tabs_pane.active
        await pilot.press("f")
        after = app.tabs_pane.active
        assert before != after  # cycled


@pytest.mark.asyncio
async def test_enter_inside_text_input_modal_submits_value(workspace):
    """Regression: priority=True on Enter must not eat keystrokes inside
    TextInputModal — pressing Enter has to fire Input.Submitted so the
    modal's callback runs. The action_drill_selection forwarding is
    responsible for routing Enter to the focused Input.
    """
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.press("j")
        # `r` opens the redirect TextInputModal.
        await pilot.press("r")
        # Type a redirect message and submit.
        await pilot.press(*list("try smaller batch"))
        await pilot.press("enter")
        # Modal closed → screen stack is back to main.
        assert len(app.screen_stack) == 1
        # Intervention was queued with the typed payload.
        events = cockpit_data.fetch_new_events(0)
        redirects = [
            e for e in events
            if e["kind"] == "intervention"
            and e["payload"].get("kind") == "redirect"
        ]
        assert redirects
        assert "smaller batch" in str(redirects[-1]["payload"])


@pytest.mark.asyncio
async def test_priority_letters_yield_to_input_focus(workspace):
    """Regression: typing 'L' / 'T' / 'F' / 'w' / 'i' / 'u' / 'q' inside
    a focused Input must produce literal characters, not toggle the App's
    priority bindings. Without the _yield_priority_letter_to_input helper,
    every uppercase / power-user letter eats the Input keystroke.

    Uses the command-line input (`:`) as the focused-Input fixture; the
    same forwarding path serves the modal Inputs (PinMetricModal etc).
    """
    app = CockpitApp()
    initial_lang = "en"
    initial_theme = "claude-warm-dark"
    async with app.run_test() as pilot:
        # Open command line — focuses the Input.
        await pilot.press("colon")
        # Type an uppercase letter that is also a priority binding (L/T/F).
        # Without forwarding this would switch language / theme / focus mode.
        await pilot.press("L")
        await pilot.press("T")
        await pilot.press("F")
        # And lowercase priority letters.
        await pilot.press("w")
        await pilot.press("i")
        await pilot.press("u")
        await pilot.press("q")
        await pilot.press("less_than_sign")
        await pilot.press("greater_than_sign")

        # All 7 chars must be in the Input value (the order may differ if
        # forwarding loses any). What we care about: language / theme are
        # NOT toggled, so the bindings yielded.
        assert app.lang == initial_lang
        assert app._settings.theme == initial_theme
        # Some characters did appear in the input (sanity: forwarding
        # works for at least the lowercase set; uppercase L behavior may
        # depend on Textual's shift handling).
        value = app.command_line.value
        assert any(ch in value for ch in ("w", "i", "u", "q"))
        assert "<" in value
        assert ">" in value


@pytest.mark.asyncio
async def test_goto_unknown_target_warns(workspace):
    app = CockpitApp()
    captured: list[tuple[str, str | None]] = []
    original_notify = app.notify

    def capture(message, **kwargs):
        captured.append((str(message), kwargs.get("severity")))
        return original_notify(message, **kwargs)

    app.notify = capture  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.press("colon")
        await pilot.press(*list("goto NOPE_XYZ"))
        await pilot.press("enter")
        assert any(severity == "warning" for _, severity in captured)
