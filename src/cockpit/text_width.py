"""Monospace terminal cell-width helpers.

``len()`` returns *character count* but the cockpit renders into a
monospace terminal where CJK ideographs, fullwidth punctuation, and a
few symbol glyphs occupy **two cells** while ASCII / Latin-1 / Greek /
Cyrillic occupy **one**. Anywhere the cockpit needs to align text by
visible width — right-aligning a HUD chip, fitting a timeline label
into a fixed-width bar, computing how many activity-card title columns
remain — it must use :func:`cell_width` instead of ``len``.

The implementation uses :mod:`unicodedata.east_asian_width` rather than
the third-party ``wcwidth`` package: this is one tiny extra dependency
to avoid, and ``east_asian_width`` covers every script the cockpit's
i18n table actually uses (en + zh-CN today; could extend to ja / ko
trivially since their CJK glyphs map to the same ``W`` / ``F``
categories).

Combining marks (Unicode category ``Mn``) contribute 0 cells — they
stack on top of the preceding base character. This matters for any
language with diacritics; today the cockpit i18n table doesn't use
any, but the helper is correct so future i18n contributors don't
have to remember.

Emoji and emoji ZWJ sequences are out of scope: the cockpit explicitly
forbids emoji glyphs (see ADR 0003 / cockpit-keys.md), so this helper
does not implement the much hairier grapheme-cluster rules emoji
require.
"""

from __future__ import annotations

import unicodedata


def cell_width(text: str) -> int:
    """Return the number of monospace cells *text* occupies when rendered.

    - CJK ideographs, fullwidth Latin, and Asian punctuation
      (``east_asian_width`` ``"W"`` / ``"F"``) → 2 cells each.
    - Combining marks (``unicodedata.category`` starts with ``"M"``) →
      0 cells each.
    - Everything else → 1 cell each.

    The function is pure / deterministic and does not touch any
    Textual / terminal state, so it is safe to call from anywhere
    including module-load time.
    """
    total = 0
    for ch in text:
        if not ch:
            continue
        category = unicodedata.category(ch)
        if category.startswith("M"):
            continue
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 2
        else:
            total += 1
    return total


def truncate_to_width(text: str, width: int, *, ellipsis: str = "…") -> str:
    """Trim *text* so it fits within *width* terminal cells.

    Appends ``ellipsis`` when truncation happens — the typographic ``…``
    is one cell on every terminal the cockpit targets and reads cleanly
    in both English and Chinese, so it is the default. Pass an empty
    string to truncate silently.

    Returns *text* unchanged when it already fits or when ``width`` is
    too small to even contain the ellipsis (degenerate input — better
    to return *something* than crash).
    """
    if width <= 0:
        return ""
    if cell_width(text) <= width:
        return text
    ellipsis_w = cell_width(ellipsis)
    budget = max(0, width - ellipsis_w)
    if budget <= 0:
        # The ellipsis itself doesn't fit. Return the head of the text
        # so callers still see *something* meaningful.
        return _take_cells(text, width)
    return _take_cells(text, budget) + ellipsis


def pad_to_width(text: str, width: int, *, side: str = "right") -> str:
    """Pad *text* with spaces so it fills exactly *width* terminal cells.

    ``side="right"`` pads on the right (text left-aligned); ``"left"``
    pads on the left (text right-aligned); ``"center"`` distributes
    padding to both sides. Text already at or above *width* is
    returned unchanged — :func:`truncate_to_width` is the matching
    truncation primitive for callers that need both.
    """
    current = cell_width(text)
    if current >= width:
        return text
    pad = width - current
    if side == "left":
        return " " * pad + text
    if side == "center":
        left = pad // 2
        return " " * left + text + " " * (pad - left)
    return text + " " * pad


def _take_cells(text: str, width: int) -> str:
    """Return the longest prefix of *text* with cell width ≤ *width*."""
    out: list[str] = []
    used = 0
    for ch in text:
        category = unicodedata.category(ch)
        if category.startswith("M"):
            out.append(ch)
            continue
        ch_w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + ch_w > width:
            break
        out.append(ch)
        used += ch_w
    return "".join(out)


__all__ = ["cell_width", "pad_to_width", "truncate_to_width"]
