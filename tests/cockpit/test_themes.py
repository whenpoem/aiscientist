"""Tests for the cockpit theme registry + token resolver.

Covers static structural invariants on the four bundled themes (every theme
defines every kind token, names are unique, the cycle order is stable),
plus the runtime behavior of ``update_theme_vars`` / ``color`` / ``style``
when no App is running.
"""

from __future__ import annotations

import pytest

from cockpit.theme import (
    ALL_THEMES,
    color,
    default_theme_name,
    get_theme,
    kind_color,
    next_theme,
    reset_theme_vars,
    style,
    theme_names,
    update_theme_vars,
)


@pytest.fixture(autouse=True)
def _isolate_theme_state():
    """Reset the in-process color cache around each test so order doesn't
    matter and a stray theme switch can't leak into the next case."""
    reset_theme_vars()
    yield
    reset_theme_vars()


def test_all_themes_have_unique_names():
    names = [theme.name for theme in ALL_THEMES]
    assert len(names) == len(set(names))
    assert "claude-warm-dark" in names
    assert "claude-warm-light" in names
    assert "claude-cool-dark" in names
    assert "claude-high-contrast" in names


def test_default_is_warm_dark():
    assert default_theme_name() == "claude-warm-dark"


def test_theme_names_returns_cycle_order():
    expected = [
        "claude-warm-dark",
        "claude-warm-light",
        "claude-cool-dark",
        "claude-high-contrast",
    ]
    assert theme_names() == expected


def test_next_theme_cycles_forward_from_each_step():
    # Walking next_theme starting at warm-dark should hit every theme exactly
    # once before returning to warm-dark.
    visited = []
    current = default_theme_name()
    for _ in range(len(ALL_THEMES)):
        visited.append(current)
        current = next_theme(current)
    assert sorted(visited) == sorted(theme_names())
    # And one more step wraps around.
    assert current == default_theme_name()


def test_next_theme_unknown_falls_back_to_first():
    assert next_theme("not-a-theme") == default_theme_name()


def test_get_theme_returns_registered_theme():
    theme = get_theme("claude-warm-dark")
    assert theme is not None
    assert theme.primary == "#d97757"


def test_get_theme_unknown_returns_none():
    assert get_theme("not-a-theme") is None


def test_color_falls_back_to_warm_dark_defaults_pre_app():
    # No app, no update_theme_vars call: should still return the warm-dark
    # palette so tests that instantiate widgets don't crash.
    assert color("primary") == "#d97757"
    assert color("foreground") == "#e8e2d8"


def test_color_unknown_token_returns_safe_default():
    # Unknown tokens fall back to a neutral foreground color rather than
    # raising — keeps render code simple.
    assert color("not-a-token").startswith("#")


def test_update_theme_vars_switches_to_cool_dark():
    update_theme_vars(get_theme("claude-cool-dark"))
    assert color("primary") == "#58a6ff"
    assert color("background") == "#0d1117"
    assert color("kind-hypothesis") == "#58a6ff"


def test_update_theme_vars_switches_to_warm_light():
    update_theme_vars(get_theme("claude-warm-light"))
    assert color("primary") == "#c45a3a"
    assert color("background") == "#faf6f0"


def test_update_theme_vars_high_contrast():
    update_theme_vars(get_theme("claude-high-contrast"))
    assert color("primary") == "#ff8800"
    assert color("foreground") == "#ffffff"
    assert color("background") == "#000000"


def test_update_theme_vars_missing_var_falls_back():
    """If a custom theme omits a kind color, the fallback table covers it."""

    class _StubTheme:
        primary = "#111111"
        secondary = "#222222"
        accent = "#333333"
        background = "#444444"
        surface = "#555555"
        panel = "#666666"
        boost = "#777777"
        foreground = "#888888"
        warning = "#999999"
        error = "#aaaaaa"
        success = "#bbbbbb"
        variables: dict[str, str] = {}

    update_theme_vars(_StubTheme())
    assert color("primary") == "#111111"
    # variables not provided → fallback to warm-dark default
    assert color("kind-hypothesis").startswith("#")


def test_kind_color_translates_underscore_to_hyphen():
    update_theme_vars(get_theme("claude-warm-dark"))
    # mem_nodes.kind values use underscore (proof_skeleton) but token names
    # use hyphen (kind-proof-skeleton). kind_color hides this from callers.
    assert kind_color("proof_skeleton") == color("kind-proof-skeleton")
    assert kind_color("hypothesis") == color("kind-hypothesis")


def test_style_composes_modifiers():
    update_theme_vars(get_theme("claude-warm-dark"))
    assert style("primary") == "#d97757"
    assert style("primary", bold=True) == "bold #d97757"
    assert style("foreground-muted", dim=True) == "dim #a89e8e"
    assert "strike" in style("kind-refuted", strike=True)


def test_every_theme_defines_every_kind_token():
    """Catch a regression where someone adds a new kind to one theme but
    forgets the others. Iterates the union of variable names and asserts
    each theme covers it."""
    all_keys: set[str] = set()
    for theme in ALL_THEMES:
        all_keys.update((theme.variables or {}).keys())
    kind_keys = {key for key in all_keys if key.startswith("kind-")}
    assert kind_keys, "expected at least one kind-* token"
    for theme in ALL_THEMES:
        missing = kind_keys - set((theme.variables or {}).keys())
        assert not missing, f"{theme.name} missing kind tokens: {missing}"
