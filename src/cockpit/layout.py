"""Adaptive layout helper for the cockpit TUI.

Three named presets correspond to three CSS classes on ``#body-grid``:

- ``wide``    (``layout-wide``)    — 3-column grid for terminals ≥ 120 cols.
- ``narrow``  (``layout-narrow``)  — 2-column grid for 80–119 cols.
- ``single``  (``layout-single``)  — single-pane focus mode (any width;
                                     also used for terminals < 80 cols).

The ``focus`` preset name is an alias for ``single`` exposed in user
settings — it preserves the user's intent ("I want focus mode") even when
the terminal is wide enough for 3 columns. ``resolve_for_width`` reflects
this: a saved ``focus`` preset always returns ``single``; ``wide`` and
``narrow`` clamp down to the largest preset that fits the current width.

Decoupling the math from the App lets the test suite verify the breakpoint
behavior without spinning up a real Textual run.
"""

from __future__ import annotations

# Width thresholds chosen to keep each pane's content readable. The middle
# column needs ~50 cols for detail text + tabs; the side columns need ~30
# each. Below 120 cols we collapse to 2 columns; below 80 we collapse to
# single-pane focus mode regardless of user preference.
WIDE_MIN_WIDTH = 120
NARROW_MIN_WIDTH = 80

LAYOUT_WIDE = "wide"
LAYOUT_NARROW = "narrow"
LAYOUT_SINGLE = "single"
LAYOUT_FOCUS = "focus"  # user-facing alias for "single" (intentional)

ALL_PRESETS: tuple[str, ...] = (LAYOUT_WIDE, LAYOUT_NARROW, LAYOUT_SINGLE, LAYOUT_FOCUS)


def normalize_preset(preset: str | None) -> str:
    """Coerce a stored preset name to a known one. Unknown → wide."""
    if preset in ALL_PRESETS:
        return preset
    return LAYOUT_WIDE


def resolve_for_width(preset: str | None, width: int) -> str:
    """Return the active layout class given a saved preset + current width.

    - User asked for ``focus`` / ``single`` → always single (don't override
      the user's intent just because the terminal is wide).
    - User asked for ``wide`` but the terminal is narrow → step down.
    - Below ``NARROW_MIN_WIDTH`` we always single-pane regardless.
    """
    saved = normalize_preset(preset)
    if saved in (LAYOUT_FOCUS, LAYOUT_SINGLE):
        return LAYOUT_SINGLE
    if width < NARROW_MIN_WIDTH:
        return LAYOUT_SINGLE
    if width < WIDE_MIN_WIDTH:
        return LAYOUT_NARROW
    return LAYOUT_WIDE


def css_class_for(active: str) -> str:
    """Return the ``layout-<name>`` CSS class for a resolved layout name."""
    if active == LAYOUT_SINGLE:
        return "layout-single"
    if active == LAYOUT_NARROW:
        return "layout-narrow"
    return "layout-wide"


def all_layout_classes() -> tuple[str, ...]:
    """Class names that should be removed when switching layouts."""
    return ("layout-wide", "layout-narrow", "layout-single")
