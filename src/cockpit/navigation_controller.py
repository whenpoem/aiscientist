"""Stateful pane navigation for the Cockpit application."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .action_router import (
    FOCUS_ORDER,
    cycle_right_tab,
    focus_relative,
    jump_cursor,
    move_cursor,
    move_horizontal,
)

if TYPE_CHECKING:
    from .app import CockpitApp


class NavigationController:
    """Own pane focus and cursor transitions while the App keeps bindings."""

    def __init__(self, app: CockpitApp) -> None:
        self.app = app

    def focus(self, pane_name: str) -> None:
        app = self.app
        if pane_name == "events":
            pane_name = "activity"
        if pane_name not in FOCUS_ORDER:
            pane_name = "tree"
        app.focused_pane = pane_name
        pane_getters = {
            "tree": lambda: app.tree_pane,
            "detail": lambda: app.detail_pane,
            "activity": lambda: app.activity_pane,
            "events": lambda: app.events_pane,
            "tabs": lambda: app.tabs_pane.current_table(),
        }
        try:
            pane_getters[pane_name]().focus()
        except Exception:  # pragma: no cover - Textual teardown race
            return

    def focus_relative(self, delta: Literal[-1, 1]) -> None:
        focus_relative(self.app, delta)

    def move_cursor(self, delta: Literal[-1, 1]) -> None:
        move_cursor(self.app, delta)

    def move_horizontal(self, delta: Literal[-1, 1]) -> None:
        move_horizontal(self.app, delta)

    def jump(self, where: Literal["top", "bottom"]) -> None:
        jump_cursor(self.app, where)

    def cycle_right_tab(self) -> None:
        cycle_right_tab(self.app)

    def resolve_drill_pane(self) -> str:
        """Resolve the pane that owns the currently focused widget."""
        app = self.app
        try:
            focused = app.focused
            widget = focused
            while widget is not None:
                if widget is app.tree_pane:
                    return "tree"
                if widget is app.tabs_pane:
                    return "tabs"
                if widget is app.events_pane:
                    return "events"
                if widget is app.activity_pane:
                    return "activity"
                if widget is app.detail_pane:
                    return "detail"
                widget = getattr(widget, "parent", None)
        except Exception:  # pragma: no cover - defensive during screen changes
            pass
        return app.focused_pane


__all__ = ["NavigationController"]
