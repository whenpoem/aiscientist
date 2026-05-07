"""Command palette provider for the cockpit TUI.

Textual ships a built-in command palette (Ctrl+P) but exposes only system
commands by default. This module registers a custom :class:`Provider` so
every cockpit action becomes searchable + executable from the palette.

Why a palette in addition to keyboard shortcuts?
- Discoverability: most users won't read 30 keybindings up front; the
  palette lets them type a fragment ("theme", "approve", "lean") and find
  the action without leaving the keyboard.
- i18n: each command's display name and description go through ``t``, so
  a Chinese user types "切换主题" and finds the theme cycler.
- Single source of truth: every action surfaced here is also bound to a
  keyboard shortcut, so the palette stays in sync with the app's actual
  capabilities (no orphan commands).

Newly added "discoverable" entries (no keyboard shortcut yet) live in this
file too — e.g. "switch theme to <name>" lets the user jump directly to a
specific theme rather than cycling through all four.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.command import DiscoveryHit, Hit, Hits, Provider

from .i18n import t
from .theme import theme_names


def cockpit_action_entries(lang: str) -> Iterable[tuple[str, str, str]]:
    """Yield ``(display_text, keyboard_hint, action_name)`` triples for
    every cockpit action exposed via the command palette.

    Pulled out as a free function so unit tests can enumerate the surface
    without instantiating a full Textual ``Provider`` (which requires a
    live screen + match-style internals).

    ``action_name`` matches methods on ``CockpitApp`` (without the
    ``action_`` prefix) so dispatch goes through ``run_action``.
    """
    # Empirical actions
    yield (t(lang, "approve_reject"), "y / n", "approve_node")
    yield (t(lang, "redirect_constrain"), "r / c", "redirect_node")
    yield (t(lang, "mark_refuted"), "m", "mark_refuted")
    yield (t(lang, "pin_metric"), "p", "pin_metric")
    yield (t(lang, "halt_agent"), "H", "halt_agent")
    # Display toggles
    yield (t(lang, "toggle_time"), "t", "toggle_timestamp_mode")
    yield (t(lang, "toggle_refuted"), "s", "toggle_refuted")
    yield (t(lang, "toggle_language"), "L", "toggle_language")
    yield (t(lang, "cycle_theme"), "T", "cycle_theme")
    yield (
        t(lang, "filter") + " — focus pane",
        "/",
        "open_filter",
    )
    yield (t(lang, "command_mode"), ":", "open_command")
    yield ("Focus mode", "F", "toggle_focus")
    yield (t(lang, "quit"), "q", "quit_requested")


class CockpitCommands(Provider):
    """Expose the cockpit action surface to Textual's command palette."""

    @property
    def _lang(self) -> str:
        # The provider runs inside the App's screen stack; ``self.app`` is
        # the running CockpitApp. ``getattr`` keeps things resilient if a
        # future Textual version restructures provider lifecycle.
        return getattr(self.app, "lang", "en")

    def _entries(self) -> Iterable[tuple[str, str, str]]:
        return cockpit_action_entries(self._lang)

    async def search(self, query: str) -> Hits:
        """Fuzzy-match the query against every action's display text."""
        matcher = self.matcher(query)
        for display, hint, action_name in self._entries():
            haystack = f"{display} {hint}"
            score = matcher.match(haystack)
            if score <= 0:
                continue
            yield Hit(
                score,
                matcher.highlight(haystack),
                self._make_runner(action_name),
                help=hint,
            )

    async def discover(self) -> Hits:
        """When the palette opens with no query, surface every action."""
        for display, hint, action_name in self._entries():
            yield DiscoveryHit(
                display,
                self._make_runner(action_name),
                help=hint,
            )

    def _make_runner(self, action_name: str):
        """Return a callback that runs the action on the app."""

        async def _run() -> None:
            await self.app.run_action(action_name)

        return _run


class ThemeSwitcherCommands(Provider):
    """Direct theme jumps. ``Ctrl+P`` then "warm" picks claude-warm-dark or
    -light depending on which fuzzy-matches first; users no longer need to
    cycle T four times to get to a specific theme."""

    @property
    def _lang(self) -> str:
        return getattr(self.app, "lang", "en")

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name in theme_names():
            label = t(self._lang, f"theme_{name}")
            haystack = f"{label} {name}"
            score = matcher.match(haystack)
            if score <= 0:
                continue
            yield Hit(
                score,
                matcher.highlight(haystack),
                self._switcher(name),
                help=name,
            )

    async def discover(self) -> Hits:
        for name in theme_names():
            label = t(self._lang, f"theme_{name}")
            yield DiscoveryHit(label, self._switcher(name), help=name)

    def _switcher(self, name: str):
        async def _run() -> None:
            self.app._apply_theme(name, persist=True, notify=True)

        return _run
