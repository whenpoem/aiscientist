"""Theme helpers for the cockpit TUI."""

from __future__ import annotations

from pathlib import Path

THEME_PATH = Path(__file__).with_name("cockpit.tcss")


def load_theme() -> str:
    return THEME_PATH.read_text(encoding="utf-8")
