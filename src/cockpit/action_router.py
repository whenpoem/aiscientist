"""Keyboard action routing across Cockpit panes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .app import CockpitApp


FOCUS_ORDER = ("tree", "detail", "activity", "tabs")


def focus_relative(app: CockpitApp, delta: Literal[-1, 1]) -> None:
    """Cycle app panes, or forward focus movement to an open modal."""
    if len(app.screen_stack) > 1:
        top = app.screen_stack[-1]
        try:
            top.focus_next() if delta > 0 else top.focus_previous()
        except Exception:  # pragma: no cover - defensive
            pass
        return
    index = FOCUS_ORDER.index(app.focused_pane)
    app._set_focus(FOCUS_ORDER[(index + delta) % len(FOCUS_ORDER)])  # noqa: SLF001


def move_cursor(app: CockpitApp, delta: Literal[-1, 1]) -> None:
    if app.focused_pane == "tree":
        app.tree_pane.move_cursor_by(delta)
        app.selected_node_id = app.tree_pane.current_node_id()
    elif app.focused_pane == "tabs":
        app.tabs_pane.move_cursor_by(delta)
    app._refresh_detail()  # noqa: SLF001


def move_horizontal(app: CockpitApp, delta: Literal[-1, 1]) -> None:
    if app.focused_pane == "tree":
        if delta < 0:
            app.tree_pane.collapse_current()
        else:
            app.tree_pane.expand_current()
        return
    focus_relative(app, delta)


def jump_cursor(app: CockpitApp, where: Literal["top", "bottom"]) -> None:
    suffix = "top" if where == "top" else "bottom"
    if app.focused_pane == "tree":
        getattr(app.tree_pane, f"move_cursor_to_{suffix}")()
        app.selected_node_id = app.tree_pane.current_node_id()
    elif app.focused_pane == "tabs":
        getattr(app.tabs_pane, f"move_cursor_to_{suffix}")()
    app._refresh_detail()  # noqa: SLF001


def cycle_right_tab(app: CockpitApp) -> None:
    app.tabs_pane.cycle_tab()
    app._refresh_detail()  # noqa: SLF001


__all__ = [
    "FOCUS_ORDER",
    "cycle_right_tab",
    "focus_relative",
    "jump_cursor",
    "move_cursor",
    "move_horizontal",
]
