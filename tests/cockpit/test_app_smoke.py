from __future__ import annotations

import pytest

from cockpit import data as cockpit_data
from cockpit.app import CockpitApp
from cockpit.panes import HypothesisTreePane


@pytest.mark.asyncio
async def test_cockpit_app_smoke(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    verify_impl = workspace["verify_mcp.impl"]

    root = memory_impl.propose_hypothesis("Tune dropout for ViT")
    memory_impl.attach_evidence(root["node_id"], "Held-out accuracy moved up", "supports")
    verify_impl.pin_metric(
        claim="accuracy",
        value="0.93",
        session_id="imagenet",
        source_command="train.py",
        note="seed 0",
    )

    app = CockpitApp()

    async with app.run_test() as pilot:
        tree = app.query_one(HypothesisTreePane)
        assert tree.visible_node_ids()
        assert app.selected_node_id is not None

        await pilot.press("j")
        assert tree.current_node_id() is not None

        await pilot.press("p")
        await pilot.press(*list("imagenet"))
        await pilot.press("tab")
        await pilot.press(*list("accuracy"))
        await pilot.press("tab")
        await pilot.press(*list("0.94"))
        await pilot.press("enter")

        await pilot.press("H")
        await pilot.press("y")

        claims = app.tabs_pane.claims_rows
        assert any(row["metric"] == "accuracy" for row in claims)

    assert cockpit_data.fetch_counts()["interventions"] >= 1
    events = cockpit_data.fetch_new_events(0)
    assert any(
        event["kind"] == "intervention" and event["payload"].get("kind") == "halt"
        for event in events
    )


@pytest.mark.asyncio
async def test_filter_escape_clears_active_tree_filter(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")
    memory_impl.propose_hypothesis("Increase batch size")

    app = CockpitApp()

    async with app.run_test() as pilot:
        tree = app.query_one(HypothesisTreePane)

        await pilot.press("/")
        await pilot.press(*list("dropout"))
        await pilot.press("enter")

        assert app._pane_filters["tree"] == "dropout"
        assert len(tree.visible_node_ids()) == 1
        assert "filter: dropout" in tree.border_title

        await pilot.press("/")
        await pilot.press("escape")

        assert app._pane_filters["tree"] == ""
        assert len(tree.visible_node_ids()) == 2
        assert "filter:" not in tree.border_title


@pytest.mark.asyncio
async def test_language_toggle_localizes_core_tui_labels(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()

    async with app.run_test() as pilot:
        assert "Hypothesis Tree" in app.tree_pane.border_title

        await pilot.press("L")

        assert app.lang == "zh"
        assert "假设树" in app.tree_pane.border_title
        assert "节点详情" in app.detail_pane.border_title
        assert "研究座舱" in app.status_bar.current_text
        # Context bar carries the shortcut crib in Chinese; the v4.1.0a1
        # update tightened it to "L 语言 · T 主题 · F 焦点 · ^P 命令面板".
        assert "语言" in app.context_bar.current_text
        assert "命令面板" in app.context_bar.current_text


@pytest.mark.asyncio
async def test_toggle_actions_persist_immediately(workspace, tmp_path):
    """Regression: in v4.1.0a0 the language / refuted / timestamp toggles
    only persisted on quit via on_unmount. A hard kill lost the choice.
    v4.1.0a1 makes each toggle persist immediately. This test verifies
    the settings file is written between toggles, not just at quit."""
    from cockpit.app import CockpitApp
    from cockpit.settings import default_config_path, load_settings

    config_path = default_config_path()
    if config_path.exists():
        config_path.unlink()

    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("L")  # toggle to zh
        # File should exist with lang=zh BEFORE we quit.
        assert config_path.exists(), "settings file not written on language toggle"
        loaded = load_settings(config_path)
        assert loaded.lang == "zh"

        await pilot.press("s")  # toggle show_refuted
        loaded = load_settings(config_path)
        assert loaded.show_refuted is True

        await pilot.press("t")  # toggle relative_timestamps
        loaded = load_settings(config_path)
        assert loaded.relative_timestamps is True


@pytest.mark.asyncio
async def test_focused_pane_restored_on_relaunch(workspace):
    """When a previous session ended with focus on the events pane, the
    next launch should start with events focused — not always tree.
    Regression for v4.1.0a0 hardcoded `_set_focus("tree")` in on_mount."""
    from cockpit.app import CockpitApp
    from cockpit.settings import default_config_path, load_settings

    config_path = default_config_path()
    if config_path.exists():
        config_path.unlink()

    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    # First session: focus events, then exit.
    app1 = CockpitApp()
    async with app1.run_test(size=(160, 40)) as pilot:
        await pilot.press("3")
        assert app1.focused_pane == "events"
    saved = load_settings(config_path)
    assert saved.focused_pane == "events"

    # Second session: should boot with events focused.
    app2 = CockpitApp()
    async with app2.run_test(size=(160, 40)):
        assert app2.focused_pane == "events", (
            f"focused_pane not restored from settings (got {app2.focused_pane!r})"
        )


@pytest.mark.asyncio
async def test_relaunch_with_tabs_focused_does_not_crash(workspace):
    """Regression: when the saved focused_pane is 'tabs', on_mount used to
    focus the inner DataTable, which bubbled Focused into TabbedContent's
    not-yet-fully-composed _watch_active and crashed with NoMatches.

    Subclassing TabbedContent with a custom compose() prevents Textual
    from injecting ContentTabs / ContentSwitcher in time, so the deferral
    via call_after_refresh isn't enough. The pragmatic fix downgrades a
    saved 'tabs' focus to 'tree' on boot — the user can press '4' to
    re-focus tabs once the cockpit is running."""
    from cockpit.app import CockpitApp
    from cockpit.settings import (
        CockpitSettings,
        default_config_path,
        save_settings,
    )

    config_path = default_config_path()
    save_settings(CockpitSettings(focused_pane="tabs"), config_path)

    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    # The whole point of the test is that this doesn't raise during mount.
    app = CockpitApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        # Downgraded to tree (documented behaviour). User can press '4'
        # later to re-focus tabs once they're ready, but the boot itself
        # must not crash.
        assert app.focused_pane == "tree"


@pytest.mark.asyncio
async def test_relaunch_with_stale_focus_layout_starts_full_layout(workspace):
    """A saved focus layout from older builds should not make startup look
    like Detail / Events / Tabs disappeared."""
    from textual.containers import Container

    from cockpit.app import CockpitApp
    from cockpit.settings import (
        CockpitSettings,
        default_config_path,
        load_settings,
        save_settings,
    )

    config_path = default_config_path()
    save_settings(CockpitSettings(layout_preset="focus"), config_path)

    app = CockpitApp()
    async with app.run_test(size=(160, 40)):
        body = app.query_one("#body-grid", Container)
        assert "layout-wide" in body.classes
        assert "layout-single" not in body.classes

    saved = load_settings(config_path)
    assert saved.layout_preset == "wide"


@pytest.mark.asyncio
async def test_focus_toggle_restores_prior_layout_preset(workspace):
    """F-then-F should return to the user's prior preset, not always wide.
    Regression for the v4.1.0a0 toggle that hardcoded LAYOUT_WIDE on exit."""
    from cockpit.app import CockpitApp

    app = CockpitApp()
    async with app.run_test(size=(160, 40)) as pilot:
        # Pretend the user is on narrow (we set it directly to dodge the
        # auto-resolve at this terminal size, which would clamp narrow→wide).
        app._settings.layout_preset = "narrow"

        await pilot.press("F")  # enter focus
        assert app._settings.layout_preset == "focus"

        await pilot.press("F")  # exit focus
        assert app._settings.layout_preset == "narrow", (
            f"focus exit clobbered prior preset (got {app._settings.layout_preset!r})"
        )


@pytest.mark.asyncio
async def test_focus_layout_is_not_persisted_as_startup_default(workspace):
    """F can enter focus mode for the current session, but a hard restart
    should still open the full dashboard."""
    from cockpit.app import CockpitApp
    from cockpit.settings import default_config_path, load_settings

    config_path = default_config_path()
    if config_path.exists():
        config_path.unlink()

    app = CockpitApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("F")
        assert app._settings.layout_preset == "focus"
        assert load_settings(config_path).layout_preset == "wide"


@pytest.mark.asyncio
async def test_tui_uses_context_bar_instead_of_default_footer(workspace):
    """The Textual Footer renders static English binding labels. The cockpit
    has its own localized ContextBar, so the default Footer should not be in
    the DOM."""
    from textual.widgets import Footer

    from cockpit.app import CockpitApp

    app = CockpitApp(lang="zh")
    async with app.run_test(size=(80, 24)):
        assert list(app.query(Footer)) == []
        assert "语言" in app.context_bar.current_text


@pytest.mark.asyncio
async def test_compact_hud_for_80_col_terminal(workspace):
    from cockpit.app import CockpitApp

    app = CockpitApp(lang="zh")
    async with app.run_test(size=(80, 24)):
        assert "研究座舱" in app.status_bar.current_text
        assert "未验证" not in app.status_bar.current_text
        assert "留出" not in app.status_bar.current_text


@pytest.mark.asyncio
async def test_real_startup_common_click_and_key_paths_do_not_crash(workspace):
    """Exercise the paths that are painful in a real TUI session: clicking
    panes, cycling tabs, opening/canceling modals, toggling theme/language,
    and switching focus inside an 80-column terminal."""
    from cockpit.app import CockpitApp

    memory_impl = workspace["memory_mcp.impl"]
    root = memory_impl.propose_hypothesis("Tune dropout for ViT")
    memory_impl.attach_evidence(root["node_id"], "Held-out accuracy moved up", "supports")

    app = CockpitApp(lang="zh")
    async with app.run_test(size=(80, 24)) as pilot:
        for target in ("#tree-pane", "#detail-pane", "#events-pane", "#tabs-pane"):
            await pilot.click(target, offset=(2, 1))
            await pilot.pause()

        for key in (
            "1",
            "j",
            "k",
            "h",
            "l",
            "g",
            "G",
            "2",
            "3",
            "4",
            "f",
            "f",
            "enter",
            "escape",
            "/",
            "escape",
            ":",
            "escape",
            "?",
            "escape",
            "T",
            "L",
            "t",
            "s",
            "R",
            "ctrl+l",
            "p",
            "escape",
            "H",
            "n",
            "r",
            "escape",
            "c",
            "escape",
            "m",
            "n",
            "F",
            "3",
            "F",
        ):
            await pilot.press(key)
            await pilot.pause()


@pytest.mark.asyncio
async def test_running_tui_pulls_backend_cockpit_events(workspace):
    """The live TUI should see events written after startup through the
    cockpit backend/MCP surface, not only rows present during initial paint."""
    from cockpit.app import CockpitApp
    from cockpit.mcp_server import record_note

    app = CockpitApp()
    async with app.run_test(size=(120, 30)) as pilot:
        start_id = app.last_event_id
        record_note("live backend link check")
        await pilot.pause(1.2)

        assert app.last_event_id > start_id
        assert any(
            row["kind"] == "note"
            and row.get("payload", {}).get("text") == "live backend link check"
            for row in app.events_pane._rows
        )


@pytest.mark.asyncio
async def test_event_dispatch_refreshes_only_affected_panes(workspace, monkeypatch):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()

    async with app.run_test():
        counters = {
            "graph": 0,
            "failures": 0,
            "claims": 0,
            "literature": 0,
            "counts": 0,
            "detail": 0,
        }

        monkeypatch.setattr(
            app,
            "_refresh_graph",
            lambda: counters.__setitem__("graph", counters["graph"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_failures",
            lambda: counters.__setitem__("failures", counters["failures"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_claims",
            lambda: counters.__setitem__("claims", counters["claims"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_literature",
            lambda: counters.__setitem__("literature", counters["literature"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_counts",
            lambda: counters.__setitem__("counts", counters["counts"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_detail",
            lambda: counters.__setitem__("detail", counters["detail"] + 1),
        )

        app._dispatch_events(
            [
                {"kind": "graph_delta"},
                {"kind": "failure_added"},
                {"kind": "seed_run_recorded"},
            ]
        )

        assert counters == {
            "graph": 1,
            "failures": 1,
            "claims": 1,
            "literature": 0,
            "counts": 1,
            "detail": 1,
        }
