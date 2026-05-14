"""Activity pane — primary visual surface for ongoing research actions.

Renders the list of :class:`cockpit.activity.ActivityCard` instances
returned by :func:`cockpit.activity.aggregate_from_db` as a vertical
stack of Rich panels. Each card body shows the most recent
``recent_event_lines`` and is decorated with a severity glyph + a
family glyph + a status indicator on the title bar.

This widget is **stateless w.r.t. workflow** (ADR 0007). The App
re-derives cards every tick and calls :meth:`set_cards`; this widget
just paints. Toggling animations (``M`` key) only affects future
visual flourishes — the current implementation is static rendering.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from cockpit.activity import (
    FAMILY_COLOR_TOKEN,
    FAMILY_GLYPH,
    SEVERITY_COLOR_TOKEN,
    SEVERITY_GLYPH,
    ActivityCard,
)
from cockpit.i18n import t
from cockpit.theme import color
from cockpit.theme import style as theme_style


class ActivityPane(VerticalScroll):
    """Scrollable list of activity cards.

    Each tick the App calls :meth:`set_cards` with a fresh list; the
    pane renders the panels into a single inner Static. The Static
    swap is cheap and keeps the VerticalScroll's scrollbar state
    consistent across ticks.
    """

    DEFAULT_CSS = """
    ActivityPane {
        background: $surface;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="activity-pane")
        self.classes = "pane"
        self.lang = "en"
        self._cards: list[ActivityCard] = []
        self._filter_text = ""
        self._body = Static("", id="activity-pane-body")
        self.border_title = "Activity"

    def compose(self):
        yield self._body

    def on_mount(self) -> None:
        self.border_title = t(self.lang, "activity_title")
        self._redraw()

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.border_title = t(self.lang, "activity_title")
        self._redraw()

    def set_cards(self, cards: list[ActivityCard]) -> None:
        """Replace the rendered card list. Idempotent; safe to call
        every tick even when nothing changed.
        """
        self._cards = list(cards)
        self._redraw()

    def set_filter_text(self, filter_text: str) -> None:
        self._filter_text = filter_text.strip().lower()
        self._redraw()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _redraw(self) -> None:
        cards = self._visible_cards()
        if not cards:
            self._body.update(
                Text(t(self.lang, "activity_empty"), style=color("foreground-subtle"))
            )
            return
        panels: list[RenderableType] = []
        for card in cards:
            panels.append(self._render_card(card))
        # Separators between cards: blank line. Rich's Group composes
        # them in order.
        body: list[RenderableType] = []
        for i, p in enumerate(panels):
            if i:
                body.append(Text(""))
            body.append(p)
        self._body.update(Group(*body))

    def _visible_cards(self) -> list[ActivityCard]:
        if not self._filter_text:
            return list(self._cards)
        needle = self._filter_text
        visible: list[ActivityCard] = []
        for card in self._cards:
            haystack = " ".join(
                [
                    card.family,
                    card.title,
                    card.focus_node_id or "",
                    card.status,
                    card.severity,
                    " ".join(str(line) for line in card.recent_event_lines),
                    " ".join(
                        f"{key} {value}" for key, value in card.summary_fields.items()
                    ),
                ]
            ).lower()
            if needle in haystack:
                visible.append(card)
        return visible

    def _render_card(self, card: ActivityCard) -> Panel:
        family_token = FAMILY_COLOR_TOKEN.get(card.family, "foreground")
        family_glyph = FAMILY_GLYPH.get(card.family, "·")
        severity_glyph = SEVERITY_GLYPH.get(card.severity, " ")
        severity_token = SEVERITY_COLOR_TOKEN.get(card.severity, "severity-info")
        status_glyph = _status_glyph(card.status)
        # Title bar text: ``<sevglyph> <familyglyph> family · focus  ━━ status``
        title = Text()
        title.append(severity_glyph + " ", style=theme_style(severity_token, bold=True))
        title.append(family_glyph + " ", style=theme_style(family_token, bold=True))
        title.append(card.title, style=theme_style(family_token, bold=True))
        # Status badge in muted colour, right-aligned visually via padding.
        title.append("   ")
        title.append(
            status_glyph + " " + t(self.lang, f"activity_status_{card.status}"),
            style=color(_status_color_token(card.status)),
        )

        body_lines: list[Text] = []
        # Summary fields (e.g. intervention.kinds) — one line of KV.
        for key, value in card.summary_fields.items():
            line = Text()
            line.append(f"{key}: ", style=color("foreground-muted"))
            if isinstance(value, list):
                line.append(", ".join(str(v) for v in value), style=color("foreground"))
            else:
                line.append(str(value), style=color("foreground"))
            body_lines.append(line)
        # If card has more events than shown, prefix with a "▸ N earlier" hint.
        hidden = card.event_count - len(card.recent_event_lines)
        if hidden > 0:
            body_lines.append(
                Text(
                    t(self.lang, "activity_more_events", count=hidden),
                    style=color("foreground-subtle"),
                )
            )
        # Event-by-event lines.
        for line in card.recent_event_lines:
            body_lines.append(Text(line, style=color("foreground-muted")))
        # Age footer.
        age_text = _relative_age(card.last_at)
        if age_text:
            body_lines.append(
                Text(
                    t(self.lang, "activity_card_age", age=age_text),
                    style=color("foreground-subtle"),
                )
            )

        return Panel(
            Group(*body_lines) if body_lines else Text(""),
            title=title,
            title_align="left",
            border_style=color(severity_token if card.severity != "info" else family_token),
            padding=(0, 1),
        )


def _status_glyph(status: str) -> str:
    return {
        "running": "▸",
        "done": "✓",
        "failed": "✗",
        "blocked": "⊘",
    }.get(status, "·")


def _status_color_token(status: str) -> str:
    return {
        "running": "kind-hypothesis",
        "done": "success",
        "failed": "error",
        "blocked": "warning",
    }.get(status, "foreground-muted")


def _relative_age(iso_ts: str) -> str:
    if not iso_ts:
        return ""
    candidate = iso_ts.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(iso_ts, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed
    secs = max(0, int(delta.total_seconds()))
    if secs < 60:
        return f"{secs}s"
    minutes, secs = divmod(secs, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"
