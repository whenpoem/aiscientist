"""Theme helpers for the cockpit TUI.

Exports both the static stylesheet path (for ``App.CSS_PATH``) and the
runtime theme registry / token accessors (for widgets that build Rich
``Text`` styles dynamically).
"""

from __future__ import annotations

from pathlib import Path

from .themes import (
    ALL_THEMES,
    COOL_DARK,
    HIGH_CONTRAST,
    WARM_DARK,
    WARM_LIGHT,
    default_theme_name,
    get_theme,
    next_theme,
    theme_names,
)
from .tokens import (
    color,
    kind_color,
    reset_theme_vars,
    style,
    update_theme_vars,
)

THEME_PATH = Path(__file__).with_name("cockpit.tcss")


def load_theme() -> str:
    return THEME_PATH.read_text(encoding="utf-8")


__all__ = [
    "ALL_THEMES",
    "COOL_DARK",
    "HIGH_CONTRAST",
    "THEME_PATH",
    "WARM_DARK",
    "WARM_LIGHT",
    "color",
    "default_theme_name",
    "get_theme",
    "kind_color",
    "load_theme",
    "next_theme",
    "reset_theme_vars",
    "style",
    "theme_names",
    "update_theme_vars",
]
