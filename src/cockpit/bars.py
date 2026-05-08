"""Tiny ASCII / Unicode bar primitives for cockpit panes.

Two flavors:

* :func:`progress_bar` — filled vs empty (``▓░``) for resource budgets
  (held-out queries, token budgets, etc.). Shows a ratio in ``[0, 1]``.
* :func:`strength_bar` — a marker (``▮``) on a horizontal track (``─``)
  for a value that lives somewhere in a ``[low, high]`` range. Used for
  Bradley-Terry strength so the user gets a direction-and-magnitude cue
  in addition to the numeric ``+0.34±0.18``.

Why a dedicated module instead of dropping these into ``i18n.py`` next
to ``KIND_ICONS``? Bars are rendered, not localized; keeping them out of
the i18n table avoids the temptation to translate glyphs by language.

All glyphs render as one monospaced cell on the cockpit's target
terminals (Windows Terminal, iTerm2, mintty). No emoji-flavored chars.
"""

from __future__ import annotations

# Filled / empty cells. ▓ (medium shade) reads as "used"; ░ (light shade)
# reads as "remaining" without screaming. Heavier choices (█) over-darken
# the line in dim themes; lighter (▒) is too quiet in high-contrast.
_FILLED = "▓"
_EMPTY = "░"
# strength_bar track + marker. The track uses a thin horizontal so the
# marker pops; the marker is a vertical block so the position is exact.
_TRACK = "─"
_MARKER = "▮"


def progress_bar(used: float, total: float, width: int = 10) -> str:
    """Render ``▓▓▓░░░░░░░`` for ``used / total`` with a fixed cell width.

    - ``width`` is the total cell count (filled + empty).
    - Out-of-range inputs are clamped: negative used → 0; used > total → full.
    - ``total <= 0`` returns a neutral placeholder line so the caller's
      formatting stays aligned even when there's no data yet.
    """
    if width <= 0:
        return ""
    if total <= 0:
        return _TRACK * width
    ratio = max(0.0, min(1.0, used / total))
    filled = int(round(ratio * width))
    # Clamp filled to [0, width] in case rounding pushes it over (shouldn't
    # under the clamp above, but defensive against float weirdness).
    filled = max(0, min(width, filled))
    return _FILLED * filled + _EMPTY * (width - filled)


def strength_bar(
    value: float,
    *,
    low: float = -2.0,
    high: float = 2.0,
    width: int = 10,
) -> str:
    """Render ``──────▮───`` with the marker positioned proportional to
    where ``value`` falls within ``[low, high]``.

    The default range ``[-2, +2]`` covers the bulk of Bradley-Terry
    strength values seen in practice (the prior is N(0, 1)). Out-of-range
    values get pinned to the endpoints rather than overflowing the bar.
    """
    if width <= 1:
        return _MARKER if width == 1 else ""
    if high <= low:
        return _TRACK * width
    ratio = max(0.0, min(1.0, (value - low) / (high - low)))
    pos = int(round(ratio * (width - 1)))
    pos = max(0, min(width - 1, pos))
    return _TRACK * pos + _MARKER + _TRACK * (width - 1 - pos)
