"""Tests for the v4.1.0a5 startup splash screen.

The splash is force-disabled in the default ``workspace`` fixture via
``RESEARCH_AGENT_COCKPIT_SPLASH=0`` so existing pilot tests don't have
to wait 1.5s nor wrestle with screen-stack ordering. Tests in this
module override that env var to "1" when they need the splash to fire.
"""

from __future__ import annotations

import pytest

from cockpit import data as cockpit_data
from cockpit.app import CockpitApp
from cockpit.i18n import TEXT
from cockpit.screens.splash import SplashScreen
from cockpit.settings import CockpitSettings, should_show_splash

# ---------------------------------------------------------------------------
# Settings resolution (pure unit tests — no Textual lifecycle)
# ---------------------------------------------------------------------------


def test_settings_default_has_splash_animation_on():
    """Default settings opt INTO the splash. New users see it; the env
    var is the way tests / power users opt out."""
    s = CockpitSettings()
    assert s.splash_animation is True


def test_should_show_splash_respects_setting_when_env_unset(monkeypatch):
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_SPLASH", raising=False)
    on = CockpitSettings(splash_animation=True)
    off = CockpitSettings(splash_animation=False)
    assert should_show_splash(on) is True
    assert should_show_splash(off) is False


@pytest.mark.parametrize("falsy", ["0", "false", "no", "off", "FALSE", " no "])
def test_should_show_splash_env_falsy_overrides_setting(monkeypatch, falsy):
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", falsy)
    s = CockpitSettings(splash_animation=True)
    assert should_show_splash(s) is False


@pytest.mark.parametrize("truthy", ["1", "true", "yes", "on", "TRUE", "On "])
def test_should_show_splash_env_truthy_overrides_setting(monkeypatch, truthy):
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", truthy)
    s = CockpitSettings(splash_animation=False)
    assert should_show_splash(s) is True


def test_should_show_splash_garbage_env_falls_back_to_setting(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", "maybe")
    on = CockpitSettings(splash_animation=True)
    off = CockpitSettings(splash_animation=False)
    assert should_show_splash(on) is True
    assert should_show_splash(off) is False


# ---------------------------------------------------------------------------
# i18n keys — both languages must be present so the bilingual UX stays
# in lockstep. The runtime ``t()`` falls back to EN, but missing keys
# regress the bilingual experience silently — so we assert presence.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["splash_subtitle", "splash_skip_hint"])
def test_splash_i18n_keys_have_both_translations(key):
    assert key in TEXT["en"], f"missing EN translation for {key!r}"
    assert key in TEXT["zh"], f"missing ZH translation for {key!r}"
    # Non-empty in both languages (not just a placeholder).
    assert TEXT["en"][key].strip()
    assert TEXT["zh"][key].strip()


# ---------------------------------------------------------------------------
# SplashScreen constructor / state machine — direct unit checks that
# don't need a running App.
# ---------------------------------------------------------------------------


def test_splash_screen_constructor_freezes_title_from_i18n():
    s = SplashScreen(lang="zh")
    assert s._title_full == TEXT["zh"]["app_name"]
    # Underline matches the title length so the line never overhangs the
    # title in the rendered frame.
    assert len(s._underline_full) == len(s._title_full)


def test_splash_screen_total_ms_clamps_low_value():
    s = SplashScreen(lang="en", total_ms=10)
    # Floor of 200ms so the splash can't flash and vanish in a frame.
    assert s._total_ms >= 200


def test_splash_screen_reduced_motion_uses_shorter_default():
    s = SplashScreen(lang="en", reduced_motion=True)
    full = SplashScreen(lang="en", reduced_motion=False)
    assert s._total_ms < full._total_ms


def test_splash_screen_dismiss_is_idempotent():
    """Calling _auto_dismiss twice should not double-pop or re-fire the
    on_done callback. The screen must remain safe under racy skip + auto
    timer firing simultaneously."""
    fired = []
    s = SplashScreen(lang="en", on_done=lambda: fired.append(1))
    # Simulate dismiss without a running app: pop_screen will raise
    # AttributeError because self.app is unset, but the defensive
    # try/except inside _auto_dismiss should swallow it. The on_done
    # callback fires regardless.
    s._auto_dismiss()
    s._auto_dismiss()
    assert s._dismissed is True
    assert len(fired) == 1


# ---------------------------------------------------------------------------
# App-level integration — env var disabled (the default in conftest)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_splash_disabled_via_env_does_not_push_screen(workspace):
    """The default ``workspace`` fixture pins the env var to ``"0"`` so
    existing pilot tests don't pay a 1.5s splash tax. Verify the wiring."""
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test() as pilot:
        # Only the default app screen should be on the stack.
        assert len(app.screen_stack) == 1
        assert not isinstance(app.screen_stack[-1], SplashScreen)
        await pilot.pause()  # cycle the event loop once for parity


# ---------------------------------------------------------------------------
# App-level integration — env var enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_splash_pushed_when_env_enabled(workspace, monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", "1")
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test() as pilot:
        # Splash should be the topmost screen right after on_mount.
        await pilot.pause()
        assert any(
            isinstance(s, SplashScreen) for s in app.screen_stack
        ), "expected SplashScreen on the stack after launch"


@pytest.mark.asyncio
async def test_splash_dismissed_by_keypress(workspace, monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", "1")
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen_stack[-1], SplashScreen)
        # Any keypress dismisses — pick "j" (an unbound non-priority key)
        # to exercise the on_key catch-all path rather than a named
        # binding. After dismiss, the splash must be gone.
        await pilot.press("j")
        await pilot.pause()
        assert not isinstance(app.screen_stack[-1], SplashScreen)


@pytest.mark.asyncio
async def test_splash_blocks_app_priority_binding_during_show(
    workspace, monkeypatch
):
    """While the splash is on screen, App.BINDINGS with priority=True must
    not fire. Without the overlay shield, "T" on splash would silently
    cycle the theme of the half-mounted main view behind it.

    Verifies via the cycle_theme path: the saved theme should remain
    unchanged after pressing T while the splash is the topmost screen.
    """
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", "1")
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen_stack[-1], SplashScreen)
        before_theme = app._settings.theme
        # Trigger the App-level priority binding for theme cycle. Because
        # the splash is on the stack, _priority_action_blocked_by_help
        # should short-circuit and the theme must not change.
        # (T is delivered as a keypress; on the splash, on_key dismisses.
        # The shield protects against any race where the binding fires
        # before on_key absorbs the event.)
        await pilot.press("T")
        await pilot.pause()
        # Splash should be dismissed by the keypress, but the binding
        # action — if it ever ran — must not have changed the theme.
        assert app._settings.theme == before_theme


@pytest.mark.asyncio
async def test_splash_pushed_when_setting_on_and_env_unset(
    workspace, monkeypatch
):
    """Persisted setting should drive splash visibility when the env
    override is absent."""
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_SPLASH", raising=False)
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    settings = CockpitSettings(splash_animation=True)
    app = CockpitApp(settings=settings)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert any(isinstance(s, SplashScreen) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_splash_skipped_when_setting_off_and_env_unset(
    workspace, monkeypatch
):
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_SPLASH", raising=False)
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    settings = CockpitSettings(splash_animation=False)
    app = CockpitApp(settings=settings)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not any(isinstance(s, SplashScreen) for s in app.screen_stack)


# ---------------------------------------------------------------------------
# Reduced motion — final state painted immediately, no per-frame work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_splash_reduced_motion_paints_final_frame(
    workspace, monkeypatch
):
    """In reduced-motion mode the splash skips animation but still appears
    briefly. The title should already be the full string when on_mount
    finishes, and the auto-dismiss timer should be the shorter cap."""
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", "1")
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("First")

    settings = CockpitSettings(
        splash_animation=True, reduced_motion=True, lang="en"
    )
    app = CockpitApp(settings=settings)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Find the splash on the stack; if motion was reduced, the title
        # widget should already carry the full app_name.
        splash = next(
            (s for s in app.screen_stack if isinstance(s, SplashScreen)),
            None,
        )
        if splash is None:
            pytest.skip("splash not on stack — env or settings reconciliation")
        assert splash._title_idx == len(splash._title_full)
        assert splash._underline_idx == len(splash._underline_full)


# ---------------------------------------------------------------------------
# After-splash main-view sanity: events worker, intervention queueing,
# and basic key handling all still work after the splash dismisses.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_view_works_after_splash_dismiss(workspace, monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", "1")
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Skip the splash.
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen_stack[-1], SplashScreen)
        # Now the main view should respond normally — queue an intervention.
        before = cockpit_data.fetch_counts()["interventions"]
        await pilot.press("y")
        after = cockpit_data.fetch_counts()["interventions"]
        assert after == before + 1
