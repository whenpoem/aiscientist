"""Cold-start welcome screen (v4.2.0a3 / B2).

Shown once when the cockpit boots against an empty state (no
``state.db`` yet, or one with zero ``mem_nodes`` rows). The screen
explains what the user is looking at and points at the first-task
walkthrough — the same path the setup wizard offers at end-of-setup.

Dismiss policy mirrors the splash:

- Any key dismisses; ``?`` opens the walkthrough doc before
  dismissing; ``q`` quits the app.
- ``CockpitSettings.welcome_shown = True`` is recorded on dismiss so
  the screen never appears on a second launch.
- ``RESEARCH_AGENT_COCKPIT_WELCOME=0`` skips it entirely — used by
  tests that don't want the screen-stack ordering surprise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static

from cockpit.i18n import t
from cockpit.theme import style as theme_style


class WelcomeScreen(Screen[None]):
    """Cold-start guidance screen."""

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
        background: $background;
    }

    WelcomeScreen #welcome-frame {
        width: 76;
        height: auto;
        align: center middle;
        padding: 2 4;
        border: round $primary;
        background: $surface;
    }

    WelcomeScreen #welcome-title {
        text-align: center;
        text-style: bold;
    }

    WelcomeScreen #welcome-body {
        text-align: left;
        margin-top: 1;
    }

    WelcomeScreen #welcome-hint {
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_welcome", show=False, priority=True),
        Binding("enter", "dismiss_welcome", show=False, priority=True),
        Binding("space", "dismiss_welcome", show=False, priority=True),
        Binding("question_mark", "open_quickstart", show=False, priority=True),
        Binding("q", "quit_from_welcome", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        lang: str = "en",
        quickstart_path: Path | None = None,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._lang = lang
        self._quickstart_path = quickstart_path
        self._on_done = on_done
        self._dismissed = False

    def compose(self) -> ComposeResult:
        with Container(id="welcome-frame"):
            yield Static(
                Text(t(self._lang, "welcome_title"), style=theme_style("primary", bold=True)),
                id="welcome-title",
            )
            yield Static(
                Text(t(self._lang, "welcome_body")),
                id="welcome-body",
            )
            yield Static(
                Text(
                    t(self._lang, "welcome_hint"),
                    style=theme_style("foreground-subtle", dim=True),
                ),
                id="welcome-hint",
            )

    def on_key(self, event: events.Key) -> None:
        # The explicit bindings above already cover Enter / Space /
        # Escape / ? / q. This catch-all picks up anything else the
        # user might press and treats it as "continue to cockpit",
        # matching the splash screen's contract.
        if event.key in {"enter", "space", "escape", "question_mark", "q"}:
            return
        event.stop()
        self._auto_dismiss()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self._auto_dismiss()

    def action_dismiss_welcome(self) -> None:
        self._auto_dismiss()

    def action_open_quickstart(self) -> None:
        path = self._quickstart_path
        if path is not None and path.exists():
            try:
                from claudescientist._setup_io import open_file_with_default_app

                open_file_with_default_app(path)
            except Exception:  # pragma: no cover - defensive
                pass
        self._auto_dismiss()

    def action_quit_from_welcome(self) -> None:
        # q means quit from this screen, not "continue to cockpit".
        # Mark it seen first so a deliberate quit does not show the same
        # cold-start overlay again on the next launch.
        if self._on_done is not None:
            try:
                self._on_done()
            except Exception:  # pragma: no cover - defensive
                pass
        try:
            self.app.exit()
        except Exception:  # pragma: no cover - defensive
            self.app.exit()

    def _auto_dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        try:
            self.app.pop_screen()
        except Exception:  # pragma: no cover - defensive
            pass
        if self._on_done is not None:
            try:
                self._on_done()
            except Exception:  # pragma: no cover - defensive
                pass


__all__ = ["WelcomeScreen"]
