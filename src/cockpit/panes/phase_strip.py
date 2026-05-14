"""Phase strip — top-docked status widget for the cockpit.

Renders the result of :func:`cockpit.phase.derive_phase_from_db` as a
3-row strip:

  Row 1: ``<glyph> Now: <phase>  · since <relative time>``
  Row 2: ``focus: <node_id_a>, <node_id_b>, ...`` (skipped when none)
  Row 3: ``! <intent text>`` (skipped when empty)

The widget owns no state; the App calls :meth:`update_phase` with a
fresh :class:`Phase` each tick. Height auto-tightens to the rendered
rows so on idle the strip collapses to one line.

ADR alignment: this is a passive display widget; it does not store
workflow state nor enforce ordering (ADR 0007 ``workflow state
inferred from data``). The phase derivation lives in
``cockpit/phase.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from cockpit.i18n import t
from cockpit.phase import (
    PHASE_COLOR_TOKEN,
    PHASE_GLYPH,
    PHASES,
    Phase,
)
from cockpit.theme import color
from cockpit.theme import style as theme_style


class PhaseStripPane(Static):
    """Top-docked status strip showing current research phase + focus + intent."""

    DEFAULT_CSS = ""

    visible_setting: reactive[bool] = reactive(True)

    def __init__(self) -> None:
        super().__init__("")
        self.id = "phase-strip"
        self.lang = "en"
        self._phase: Phase = Phase(name="idle")
        self.shrink = True

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self._redraw()

    def set_visible(self, visible: bool) -> None:
        """Toggle visibility via the ``phase-strip-hidden`` class.

        Keeps the widget mounted so the app does not have to detach /
        re-attach on every toggle; the class hides via ``display: none``.
        """
        self.visible_setting = visible
        if visible:
            self.remove_class("phase-strip-hidden")
        else:
            self.add_class("phase-strip-hidden")

    def update_phase(self, phase: Phase) -> None:
        if phase.name not in PHASES:
            # Defensive: unknown phase falls back to idle rather than
            # crashing the strip on a corrupt payload.
            phase = Phase(name="idle")
        self._phase = phase
        self._redraw()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _redraw(self) -> None:
        phase = self._phase
        token = PHASE_COLOR_TOKEN.get(phase.name, "foreground")
        glyph = PHASE_GLYPH.get(phase.name, "·")

        title = t(self.lang, "phase_strip_title")
        phase_label = t(self.lang, f"phase_{phase.name}")

        line1 = Text()
        line1.append(f"{title}: ", style=color("foreground-muted"))
        line1.append(f"{glyph} ", style=theme_style(token, bold=True))
        line1.append(phase_label, style=theme_style(token, bold=True))

        if phase.name == "idle":
            line1.append("  ")
            line1.append(t(self.lang, "phase_no_activity"), style=color("foreground-subtle"))

        # Append "since <age>" when we have a valid timestamp and the
        # phase is non-idle (idle's "since" would say "now" which is
        # confusing).
        if phase.name != "idle" and phase.since:
            age = _relative_age(phase.since)
            if age:
                line1.append("  · ", style=color("foreground-subtle"))
                line1.append(
                    t(self.lang, "phase_since", age=age),
                    style=color("foreground-subtle"),
                )

        rows: list[Text] = [line1]

        if phase.focus_nodes:
            focus_line = Text()
            focus_line.append(
                t(self.lang, "phase_focus_label") + ": ",
                style=color("foreground-muted"),
            )
            focus_line.append(
                ", ".join(phase.focus_nodes),
                style=theme_style("kind-hypothesis"),
            )
            rows.append(focus_line)

        if phase.intent.strip():
            intent_line = Text()
            intent_line.append("! ", style=theme_style("warning", bold=True))
            intent_line.append(phase.intent, style=color("foreground"))
            rows.append(intent_line)

        out = Text()
        for i, row in enumerate(rows):
            if i:
                out.append("\n")
            out.append(row)
        self.update(out)


def _relative_age(iso_ts: str) -> str:
    """Render a short ``"5m"`` / ``"32s"`` style age relative to now.

    Returns empty string on parse failure rather than raising — the
    strip should keep rendering even if the timestamp is malformed.
    """
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
