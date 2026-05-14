"""Phase E4: bottom-docked event timeline strip.

Renders the most recent ``cockpit_events`` rows as a single-line
horizontal "scrubber":

    │░░·▒·▓░·····░·█·▒·······░·│

Each cell is one event; the glyph encodes severity (the Phase B
density ramp ``█ ▓ ▒ ░`` plus a base ``·`` for info-tier events).
Rightmost cell is the freshest event. Bookended with ``│`` so the
strip's edges read as borders rather than as more events.

Why not draw it the way audit-log already does?

- AuditLog scrolls vertically, line per event; users have to read
  text to perceive density.
- The horizontal density strip lets the eye answer "is the agent
  spiking activity right now?" / "did anything happen in the last
  minute?" without reading any text.

The strip is hidden by default — toggled by the ``:timeline``
command (Phase E4 reused the command palette plumbing rather than
burning another precious capital key). When visible it occupies one
docked row above the audit log; the right edge auto-updates each
poll tick because the App calls :meth:`set_events` from
``events_worker``.

Interactive scrubbing (left/right arrow keys to walk through past
events) is intentionally deferred: it would require freezing the
strip while the App ticks, which is a bigger state-machine change.
Phase E4 ships the visualisation only — the v0.3 reviewer can
flag whether the interactive form is worth a follow-up.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from cockpit.activity import (
    KIND_SEVERITY,
    SEVERITY_COLOR_TOKEN,
    SEVERITY_GLYPH,
    SEVERITY_ORDER,
)
from cockpit.i18n import t
from cockpit.theme import color
from cockpit.theme import style as theme_style


class TimelinePane(Static):
    """Horizontal event-density strip docked above the audit log."""

    def __init__(self) -> None:
        super().__init__("")
        self.id = "timeline-pane"
        self.classes = "timeline-hidden"
        self.lang = "en"
        self._events: list[dict] = []
        # Max cells we'll render. Reduces to the actual terminal width
        # at paint time so the strip never overflows; this is the
        # ceiling for how much history we'll display even on a 4K
        # console.
        self._max_cells = 200
        # Last rendered Text object kept for tests and for re-rendering
        # via :meth:`set_language` without re-doing the severity-lookup
        # walk. The widget itself stores its display state inside
        # Textual; this attribute is for inspection / test only.
        self._rendered: Text | str = ""

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self._redraw()

    def set_visible(self, visible: bool) -> None:
        """Toggle visibility via the ``timeline-hidden`` class.

        Idempotent. Keeps the widget mounted so ``set_events`` can
        keep accumulating data even when the user has the strip
        hidden — it appears already populated on next toggle-on.
        """
        if visible:
            self.remove_class("timeline-hidden")
        else:
            self.add_class("timeline-hidden")
        self._redraw()

    @property
    def is_visible(self) -> bool:
        return not self.has_class("timeline-hidden")

    def set_events(self, events: list[dict]) -> None:
        """Replace the in-memory event tail.

        ``events`` is the chronologically ordered list — same shape
        the audit log consumes. The newest event lives at index ``-1``
        which is what the strip's right edge represents.
        """
        self._events = list(events)[-self._max_cells:]
        if self.is_visible:
            self._redraw()

    def _redraw(self) -> None:
        if not self.is_visible:
            self._rendered = ""
            self.update("")
            return
        if not self._events:
            empty = Text(
                t(self.lang, "timeline_empty"), style=color("foreground-subtle")
            )
            self._rendered = empty
            self.update(empty)
            return
        # Reserve a few cells for the bracket characters and a trailing
        # label. The strip itself fills the rest.
        try:
            terminal_width = self.size.width
        except Exception:  # pragma: no cover - defensive
            terminal_width = 80
        body_budget = max(20, terminal_width - 6)
        # Pick the most recent ``body_budget`` events (one cell per).
        tail = self._events[-body_budget:]
        text = Text()
        text.append("│", style=color("foreground-muted"))
        for ev in tail:
            severity = _severity_for(ev.get("kind", ""))
            glyph = SEVERITY_GLYPH.get(severity, "·") or "·"
            token = SEVERITY_COLOR_TOKEN.get(severity, "severity-info")
            text.append(glyph, style=theme_style(token))
        text.append("│", style=color("foreground-muted"))
        # Suffix: count of events shown + total. Helps the user judge
        # whether scrolling further would buy them more context.
        suffix = t(
            self.lang,
            "timeline_caption",
            shown=len(tail),
            total=len(self._events),
        )
        text.append("  " + suffix, style=color("foreground-subtle"))
        self._rendered = text
        self.update(text)


def _severity_for(kind: str) -> str:
    """Map an event kind to its severity tier via the Phase B vocab.

    Unknown kinds default to ``info`` so they render as the base
    ``·`` cell rather than crashing or skipping the dot. ``SEVERITY_ORDER``
    is imported only to make the fallback robust against vocab edits.
    """
    sev = KIND_SEVERITY.get(kind, "info")
    if sev not in SEVERITY_ORDER:
        return "info"
    return sev
