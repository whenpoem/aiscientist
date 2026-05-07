"""Tests for the command palette providers (G4 / v4.1.0a0).

We test ``cockpit_action_entries`` directly (a free function) instead of
constructing the Textual ``Provider`` class, because the latter needs a
live screen + match-style infrastructure that's awkward to fake in unit
tests. The Provider classes themselves are thin wrappers — they delegate
to the same enumeration this test exercises.
"""

from __future__ import annotations


def test_action_entries_resolve_to_real_app_methods():
    """Every action name yielded must correspond to an ``action_<name>``
    method on ``CockpitApp``. Otherwise the palette would silently no-op
    when a user picks the entry."""
    from cockpit.app import CockpitApp
    from cockpit.commands import cockpit_action_entries

    for _display, _hint, action_name in cockpit_action_entries("en"):
        method_name = f"action_{action_name}"
        assert hasattr(CockpitApp, method_name), (
            f"Command palette references {method_name} but CockpitApp "
            "doesn't define it."
        )


def test_action_entries_localize_under_zh():
    """When the language is zh, at least one display should contain a CJK
    character. (Some legitimate labels stay ASCII like 'Lean' / 'Focus'.)"""
    from cockpit.commands import cockpit_action_entries

    displays_en = {d for d, _h, _a in cockpit_action_entries("en")}
    displays_zh = {d for d, _h, _a in cockpit_action_entries("zh")}
    assert displays_en != displays_zh, (
        "expected at least one entry to differ between en and zh, indicating "
        "that the palette respects the language setting"
    )
    assert any(
        any("一" <= ch <= "鿿" for ch in d) for d in displays_zh
    ), "expected at least one Chinese-localized entry under lang=zh"


def test_theme_switcher_lists_four_themes():
    """The theme switcher should expose every registered theme so the
    palette acts as a quick-jump."""
    from cockpit.theme import theme_names

    assert sorted(theme_names()) == sorted(
        [
            "claude-warm-dark",
            "claude-warm-light",
            "claude-cool-dark",
            "claude-high-contrast",
        ]
    )


def test_cockpit_app_registers_custom_command_providers():
    """The CockpitApp.COMMANDS class attr must include both custom providers
    so Ctrl+P surfaces cockpit actions, not just Textual's built-ins."""
    from cockpit.app import CockpitApp
    from cockpit.commands import CockpitCommands, ThemeSwitcherCommands

    assert CockpitCommands in CockpitApp.COMMANDS
    assert ThemeSwitcherCommands in CockpitApp.COMMANDS
