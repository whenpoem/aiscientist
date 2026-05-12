"""Welcome screen + cold-start detection (v4.2.0a3 / B2)."""

from __future__ import annotations

import pytest

from cockpit.app import CockpitApp
from cockpit.settings import CockpitSettings


@pytest.mark.asyncio
async def test_cold_start_pushes_welcome_screen(workspace, monkeypatch):
    """Empty mem_nodes + first launch → Welcome appears on the stack."""
    # The conftest fixture force-disables welcome by default to keep
    # all other pilot tests from wrestling with the screen-stack
    # ordering. Re-enable it for this test.
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_WELCOME", "1")
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_WELCOME", raising=False)

    from cockpit.screens import WelcomeScreen

    app = CockpitApp(settings=CockpitSettings(welcome_shown=False))
    async with app.run_test():
        assert any(isinstance(s, WelcomeScreen) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_warm_session_skips_welcome(workspace, monkeypatch):
    """Non-empty mem_nodes → Welcome is suppressed even on first launch."""
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_WELCOME", raising=False)
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("warm session marker")

    from cockpit.screens import WelcomeScreen

    app = CockpitApp(settings=CockpitSettings(welcome_shown=False))
    async with app.run_test():
        assert not any(isinstance(s, WelcomeScreen) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_welcome_shown_flag_prevents_relaunch(workspace, monkeypatch):
    """If welcome_shown=True in settings, the screen never appears even on cold start."""
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_WELCOME", raising=False)

    from cockpit.screens import WelcomeScreen

    app = CockpitApp(settings=CockpitSettings(welcome_shown=True))
    async with app.run_test():
        assert not any(isinstance(s, WelcomeScreen) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_env_var_zero_disables_welcome(workspace, monkeypatch):
    """RESEARCH_AGENT_COCKPIT_WELCOME=0 always suppresses the screen."""
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_WELCOME", "0")

    from cockpit.screens import WelcomeScreen

    app = CockpitApp(settings=CockpitSettings(welcome_shown=False))
    async with app.run_test():
        assert not any(isinstance(s, WelcomeScreen) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_dismissing_welcome_marks_shown(workspace, monkeypatch):
    """Dismissing Welcome pops it and flips welcome_shown=True.

    We drive the action directly rather than via pilot.press because
    Textual's screen-stack key routing varies subtly across versions;
    the contract we care about is "action_dismiss_welcome flips the
    setting and pops the screen", which is what production code does
    in response to the binding."""
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_WELCOME", raising=False)

    from cockpit.screens import WelcomeScreen

    app = CockpitApp(settings=CockpitSettings(welcome_shown=False))
    async with app.run_test() as pilot:
        welcome = next(
            (s for s in app.screen_stack if isinstance(s, WelcomeScreen)),
            None,
        )
        assert welcome is not None
        welcome.action_dismiss_welcome()
        await pilot.pause()
        assert not any(isinstance(s, WelcomeScreen) for s in app.screen_stack)
        assert app._settings.welcome_shown is True


@pytest.mark.asyncio
async def test_welcome_blocks_app_priority_bindings(workspace, monkeypatch):
    """Welcome is an overlay like Splash/Help: priority app keys must
    not mutate the half-mounted cockpit behind it."""
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_WELCOME", raising=False)
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", "0")

    from cockpit.screens import WelcomeScreen

    app = CockpitApp(settings=CockpitSettings(welcome_shown=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen_stack[-1], WelcomeScreen)
        before_theme = app._settings.theme
        await pilot.press("T")
        await pilot.pause()
        assert isinstance(app.screen_stack[-1], WelcomeScreen)
        assert app._settings.theme == before_theme


@pytest.mark.asyncio
async def test_welcome_q_quits_app(workspace, monkeypatch):
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_WELCOME", raising=False)
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_SPLASH", "0")

    from cockpit.screens import WelcomeScreen

    app = CockpitApp(settings=CockpitSettings(welcome_shown=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        welcome = next(
            (s for s in app.screen_stack if isinstance(s, WelcomeScreen)),
            None,
        )
        assert welcome is not None
        welcome.action_quit_from_welcome()
        await pilot.pause()
        assert app._settings.welcome_shown is True
        assert not app.is_running


@pytest.mark.asyncio
async def test_should_show_welcome_helper(workspace, monkeypatch):
    """Direct unit-test of the cold-start probe."""
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_WELCOME", raising=False)

    # Cold (empty) DB → True
    app = CockpitApp(settings=CockpitSettings(welcome_shown=False))
    assert app._should_show_welcome() is True

    # welcome_shown flag set → False
    app2 = CockpitApp(settings=CockpitSettings(welcome_shown=True))
    assert app2._should_show_welcome() is False

    # Warm DB → False
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("marker")
    app3 = CockpitApp(settings=CockpitSettings(welcome_shown=False))
    assert app3._should_show_welcome() is False
