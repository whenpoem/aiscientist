"""Cockpit startup splash (v4.1.0a6).

A brief, skippable animated intro that runs once per launch:

- Title types in character by character ("research state" / "研究状态")
- Underline draws left-to-right in the accent color
- Subtitle fades in
- Skip-hint fades in with a low-amplitude breathing pulse

The splash is a regular ``Screen`` (not a ``ModalScreen``) so the App's
default screen mounts underneath; popping the splash reveals an
already-warm UI.

Disable points:
- ``CockpitSettings.splash_animation = False`` (saved preference)
- ``RESEARCH_AGENT_COCKPIT_SPLASH=0`` env var — used by ``conftest.py``
  so existing pilot tests don't wrestle with screen-stack ordering
- ``CockpitSettings.reduced_motion = True`` paints the final state
  immediately, skipping the per-frame typewriter / underline / breath
  animations; the splash still waits for a keypress

Dismiss policy:
- Splash holds at the final frame until the user presses any key (or
  clicks). There is no timed auto-dismiss; the "press any key to
  continue" hint is literal. This was changed from a 1.5s hard cap in
  v4.1.0a6 because the cap made the hint a lie.
- Any keypress dismisses (handled in ``on_key``)
- Any mouse click dismisses (``on_click``)

Action keys (y/n/r/c/m/p/H/T/L/F/...) bound at the App level are
intentionally suppressed while the splash is the active screen — see
``CockpitApp._priority_action_blocked_by_help``, which extends to also
shield against the splash. Without that, pressing "T" during splash
would cycle the theme of the half-mounted main view behind it.
"""

from __future__ import annotations

from typing import Callable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static

from cockpit.i18n import t
from cockpit.theme import color
from cockpit.theme import style as theme_style

# Phase D: tightened splash timing.
#
# The previous defaults (typewriter 70ms/char + underline 25ms/cell +
# subtitle/hint delays + 2s logo wipe ≈ 3s total) made the splash feel
# *long* on every cockpit launch — fine the first time, hostile when
# the user opens cockpit dozens of times a day. The new defaults keep
# the cinematic shape (type-in → underline → settle) but compress to
# ~700ms total. ``reduced_motion`` still skips the per-frame work
# entirely; the env-var path is also unchanged.
_TYPE_INTERVAL_S = 0.035
_UNDERLINE_INTERVAL_S = 0.012
_SUBTITLE_DELAY_AFTER_TITLE_S = 0.10
_HINT_DELAY_AFTER_SUBTITLE_S = 0.08
# Breathing tick for the skip hint — kept slow so the screen feels
# alive while the user reads the title. 3.2s full cycle.
_HINT_BREATH_INTERVAL_S = 0.08
_HINT_BREATH_PHASES = 40

# Logo column-wipe: also compressed. ~12ms × 67 cols ≈ 0.8s.
_LOGO_INTERVAL_S = 0.012

# Min terminal size to render the logo. Below this, the splash falls
# back to its logo-less form so the layout doesn't overflow / clip.
# Picked so the default ``app.run_test()`` size (80×24) does NOT show
# the logo — existing pilot tests don't have to know about it.
_LOGO_MIN_COLS = 100
_LOGO_MIN_ROWS = 26

# ASCII-art "ClaudeScientist" — ANSI Shadow style, "Claude" stacked over
# "Scientist". Lines are padded to a uniform width (_LOGO_WIDTH) so the
# column-reveal animation paints a coherent vertical wavefront. If you
# regenerate this with a different figlet font, keep the padding step
# below — it's load-bearing for the wipe.
_LOGO_LINES_RAW: tuple[str, ...] = (
    " ██████╗██╗      █████╗ ██╗   ██╗██████╗ ███████╗",
    "██╔════╝██║     ██╔══██╗██║   ██║██╔══██╗██╔════╝",
    "██║     ██║     ███████║██║   ██║██║  ██║█████╗  ",
    "██║     ██║     ██╔══██║██║   ██║██║  ██║██╔══╝  ",
    "╚██████╗███████╗██║  ██║╚██████╔╝██████╔╝███████╗",
    " ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝",
    "███████╗ ██████╗██╗███████╗███╗   ██╗████████╗██╗███████╗████████╗",
    "██╔════╝██╔════╝██║██╔════╝████╗  ██║╚══██╔══╝██║██╔════╝╚══██╔══╝",
    "███████╗██║     ██║█████╗  ██╔██╗ ██║   ██║   ██║███████╗   ██║   ",
    "╚════██║██║     ██║██╔══╝  ██║╚██╗██║   ██║   ██║╚════██║   ██║   ",
    "███████║╚██████╗██║███████╗██║ ╚██╗██║   ██║   ██║███████║   ██║   ",
    "╚══════╝ ╚═════╝╚═╝╚══════╝╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝╚══════╝   ╚═╝   ",
)
_LOGO_WIDTH: int = max(len(line) for line in _LOGO_LINES_RAW)
_LOGO_HEIGHT: int = len(_LOGO_LINES_RAW)
_LOGO_LINES: tuple[str, ...] = tuple(
    line.ljust(_LOGO_WIDTH) for line in _LOGO_LINES_RAW
)


class SplashScreen(Screen[None]):
    """Full-window startup splash animation."""

    DEFAULT_CSS = """
    SplashScreen {
        align: center middle;
        background: $background;
    }

    SplashScreen #splash-frame {
        width: auto;
        height: auto;
        align: center middle;
        padding: 1 4;
    }

    SplashScreen #splash-logo {
        width: auto;
        text-align: center;
        margin-bottom: 1;
    }

    SplashScreen #splash-title {
        width: auto;
        text-align: center;
        text-style: bold;
    }

    SplashScreen #splash-underline {
        width: auto;
        text-align: center;
    }

    SplashScreen #splash-subtitle {
        width: auto;
        text-align: center;
        margin-top: 1;
    }

    SplashScreen #splash-hint {
        width: auto;
        text-align: center;
        margin-top: 2;
    }
    """

    # We bind a few common skip keys explicitly so they show up if the
    # binding list is ever surfaced to the user. The actual catch-all
    # "any key dismisses" lives in ``on_key`` below — bindings alone
    # would only cover the listed keys.
    BINDINGS = [
        Binding("escape", "dismiss_splash", show=False, priority=True),
        Binding("space", "dismiss_splash", show=False, priority=True),
        Binding("enter", "dismiss_splash", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        lang: str = "en",
        reduced_motion: bool = False,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._lang = lang
        self._reduced_motion = reduced_motion
        self._on_done = on_done
        # Title text comes from i18n so it switches with the chosen
        # language. We freeze the string for the duration of the splash;
        # if the user toggles language mid-splash, the new label appears
        # on the next launch, not mid-animation.
        self._title_full = t(lang, "app_name") or "research state"
        self._title_idx = 0
        self._underline_full = "━" * max(len(self._title_full), 1)
        self._underline_idx = 0
        self._dismissed = False
        # Timer handles — kept so an early skip can stop them. Textual
        # also auto-cancels timers on screen unmount, but stopping early
        # avoids a final unnecessary tick mid-pop.
        self._typewriter_timer = None
        self._underline_timer = None
        self._breath_timer = None
        self._logo_timer = None
        self._breath_phase = 0
        # Logo state. Resolved against terminal size in ``on_mount``: a
        # cramped terminal hides the logo entirely so the layout doesn't
        # clip. Once visible, the wipe advances ``_logo_idx`` from 0 to
        # ``_LOGO_WIDTH`` over ``_LOGO_INTERVAL_S`` per column.
        self._logo_idx = 0
        self._logo_hidden = True

    def compose(self) -> ComposeResult:
        with Container(id="splash-frame"):
            # Logo is composed first so it sits ABOVE the title block. It
            # may end up display:none in tiny terminals — see on_mount.
            yield Static("", id="splash-logo")
            yield Static("", id="splash-title")
            yield Static("", id="splash-underline")
            yield Static("", id="splash-subtitle")
            yield Static("", id="splash-hint")

    def on_mount(self) -> None:
        title_widget = self.query_one("#splash-title", Static)
        underline_widget = self.query_one("#splash-underline", Static)
        subtitle_widget = self.query_one("#splash-subtitle", Static)
        hint_widget = self.query_one("#splash-hint", Static)
        logo_widget = self.query_one("#splash-logo", Static)

        # Resolve whether the logo fits this terminal. We read the App
        # size rather than the screen's own size because the screen may
        # not have a layout pass yet; the App is mounted by now.
        try:
            term_size = self.app.size
            cols = int(term_size.width)
            rows = int(term_size.height)
        except Exception:  # pragma: no cover - defensive
            cols, rows = 80, 24
        self._logo_hidden = cols < _LOGO_MIN_COLS or rows < _LOGO_MIN_ROWS
        if self._logo_hidden:
            try:
                # Setting display:none collapses the widget so the title
                # block centers on the actual viewport, not below an
                # empty band where the logo would have lived.
                logo_widget.styles.display = "none"
            except Exception:  # pragma: no cover - defensive
                pass
        else:
            logo_widget.update("")

        # Start with a lone cursor so the splash never looks frozen — the
        # cursor makes the screen "alive" the instant it paints, even
        # before the first typewriter tick fires.
        title_widget.update(Text("▌", style=theme_style("accent", bold=True)))
        underline_widget.update("")
        subtitle_widget.update("")
        hint_widget.update("")
        try:
            subtitle_widget.styles.opacity = 0.0
            hint_widget.styles.opacity = 0.0
        except Exception:  # pragma: no cover - older Textual without opacity
            pass

        if self._reduced_motion:
            # Reduced motion: paint the final state and wait for keypress.
            # No per-frame animation, no auto-dismiss — same dismissal
            # contract as the animated path.
            self._paint_final_state()
            return

        # Phase 1: typewriter for the title.
        self._typewriter_timer = self.set_interval(
            _TYPE_INTERVAL_S, self._advance_typewriter
        )
        # Phase 1b: logo column-wipe. Runs in parallel with the title
        # typewriter on its own (faster) cadence so the logo finishes
        # ~2s in — slightly after the title underline, giving the splash
        # a "settling" feel as the brand mark fills in last.
        if not self._logo_hidden:
            self._logo_timer = self.set_interval(
                _LOGO_INTERVAL_S, self._advance_logo
            )
        # Schedule subsequent phases by absolute offset from "now" so the
        # schedule stays consistent if Textual coalesces ticks. After the
        # last phase (hint fade-in + breath start) the splash holds at
        # its final frame indefinitely until the user dismisses with a
        # key or click — see module docstring.
        type_duration = (len(self._title_full) + 1) * _TYPE_INTERVAL_S
        self.set_timer(type_duration, self._start_underline)
        self.set_timer(
            type_duration + _SUBTITLE_DELAY_AFTER_TITLE_S, self._show_subtitle
        )
        hint_at = (
            type_duration
            + _SUBTITLE_DELAY_AFTER_TITLE_S
            + _HINT_DELAY_AFTER_SUBTITLE_S
        )
        self.set_timer(hint_at, self._show_hint)

    # -- animation phases -------------------------------------------------

    def _advance_typewriter(self) -> None:
        if self._dismissed:
            return
        if self._title_idx >= len(self._title_full):
            self._stop_timer("_typewriter_timer")
            return
        self._title_idx += 1
        partial = self._title_full[: self._title_idx]
        self._render_title(partial, with_cursor=True)

    def _start_underline(self) -> None:
        if self._dismissed:
            return
        # Park the title without the cursor before the underline begins.
        self._render_title(self._title_full, with_cursor=False)
        self._underline_timer = self.set_interval(
            _UNDERLINE_INTERVAL_S, self._advance_underline
        )

    def _advance_underline(self) -> None:
        if self._dismissed:
            return
        if self._underline_idx >= len(self._underline_full):
            self._stop_timer("_underline_timer")
            return
        self._underline_idx += 1
        partial = self._underline_full[: self._underline_idx]
        try:
            self.query_one("#splash-underline", Static).update(
                Text(partial, style=color("accent"))
            )
        except Exception:  # pragma: no cover - defensive
            pass

    def _advance_logo(self) -> None:
        """Reveal one more column of the ASCII-art logo.

        Stops once the wipe reaches ``_LOGO_WIDTH``. Cheap when called
        after that point thanks to the early return; we still call
        ``_stop_timer`` to avoid wasted ticks.
        """
        if self._dismissed:
            return
        if self._logo_idx >= _LOGO_WIDTH:
            self._stop_timer("_logo_timer")
            return
        self._logo_idx += 1
        self._render_logo(self._logo_idx)

    def _render_logo(self, cols: int) -> None:
        """Paint the leftmost ``cols`` columns of every logo line.

        Each line is right-padded to ``_LOGO_WIDTH`` so the centred
        layout keeps the wipe rooted at the same screen X — without
        padding, ``text-align: center`` would re-center each frame as
        the visible width grows and the logo would appear to slide.
        """
        if self._logo_hidden or self._dismissed:
            return
        try:
            widget = self.query_one("#splash-logo", Static)
        except Exception:  # pragma: no cover
            return
        clamped = max(0, min(cols, _LOGO_WIDTH))
        visible = "\n".join(
            line[:clamped].ljust(_LOGO_WIDTH) for line in _LOGO_LINES
        )
        widget.update(
            Text(visible, style=theme_style("foreground-subtle", dim=True))
        )

    def _show_subtitle(self) -> None:
        if self._dismissed:
            return
        try:
            sub = self.query_one("#splash-subtitle", Static)
        except Exception:  # pragma: no cover
            return
        sub.update(
            Text(
                t(self._lang, "splash_subtitle"),
                style=theme_style("foreground-muted"),
            )
        )
        try:
            sub.styles.animate("opacity", 1.0, duration=0.3)
        except Exception:  # pragma: no cover - older Textual
            sub.styles.opacity = 1.0

    def _show_hint(self) -> None:
        if self._dismissed:
            return
        try:
            hint = self.query_one("#splash-hint", Static)
        except Exception:  # pragma: no cover
            return
        hint.update(
            Text(
                t(self._lang, "splash_skip_hint"),
                style=theme_style("foreground-subtle", dim=True),
            )
        )
        try:
            hint.styles.animate("opacity", 0.55, duration=0.25)
        except Exception:  # pragma: no cover
            hint.styles.opacity = 0.55
        # Subtle breathing pulse — gentle visual cue that the splash is
        # alive, without inviting attention away from the title.
        self._breath_timer = self.set_interval(
            _HINT_BREATH_INTERVAL_S, self._breathe_hint
        )

    def _breathe_hint(self) -> None:
        if self._dismissed:
            return
        self._breath_phase = (self._breath_phase + 1) % _HINT_BREATH_PHASES
        # Triangle wave between 0.35 and 0.65. We avoid sin() because the
        # difference is invisible at this amplitude and triangle skips a
        # math import for one calculation.
        half = _HINT_BREATH_PHASES // 2
        if self._breath_phase < half:
            opacity = 0.35 + 0.30 * (self._breath_phase / half)
        else:
            opacity = 0.65 - 0.30 * ((self._breath_phase - half) / half)
        try:
            self.query_one("#splash-hint", Static).styles.opacity = opacity
        except Exception:  # pragma: no cover
            pass

    # -- helpers ----------------------------------------------------------

    def _paint_final_state(self) -> None:
        """Render the splash in its final form without animation.

        Used for reduced-motion mode and as the snap-target when the user
        skips mid-animation.
        """
        self._title_idx = len(self._title_full)
        self._underline_idx = len(self._underline_full)
        self._logo_idx = _LOGO_WIDTH
        self._render_title(self._title_full, with_cursor=False)
        # Render the full logo if we're showing one. ``_render_logo`` is
        # idempotent and short-circuits when ``_logo_hidden`` so this is
        # safe in both branches.
        self._render_logo(_LOGO_WIDTH)
        try:
            self.query_one("#splash-underline", Static).update(
                Text(self._underline_full, style=color("accent"))
            )
            sub = self.query_one("#splash-subtitle", Static)
            sub.update(
                Text(
                    t(self._lang, "splash_subtitle"),
                    style=theme_style("foreground-muted"),
                )
            )
            sub.styles.opacity = 1.0
            hint = self.query_one("#splash-hint", Static)
            hint.update(
                Text(
                    t(self._lang, "splash_skip_hint"),
                    style=theme_style("foreground-subtle", dim=True),
                )
            )
            hint.styles.opacity = 0.55
        except Exception:  # pragma: no cover - defensive
            pass

    def _render_title(self, text: str, *, with_cursor: bool) -> None:
        try:
            widget = self.query_one("#splash-title", Static)
        except Exception:  # pragma: no cover
            return
        if with_cursor:
            content = Text()
            content.append(text, style=theme_style("foreground", bold=True))
            content.append("▌", style=theme_style("accent", bold=True))
        else:
            content = Text(text, style=theme_style("foreground", bold=True))
        widget.update(content)

    def _stop_timer(self, attr: str) -> None:
        timer = getattr(self, attr, None)
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:  # pragma: no cover
            pass
        setattr(self, attr, None)

    # -- skip / dismiss ---------------------------------------------------

    def action_dismiss_splash(self) -> None:
        """Action target for the explicit skip bindings (esc/space/enter)."""
        self._auto_dismiss()

    def on_key(self, event: events.Key) -> None:
        # Catch-all: any key skips. The named bindings above cover the
        # common skip keys with priority=True so they fire even when an
        # internal widget would otherwise claim them; the rest funnel
        # through here. ``event.stop()`` prevents the keystroke from
        # bubbling to App-level bindings (e.g. "T" cycling theme).
        event.stop()
        self._auto_dismiss()

    def on_click(self, event: events.Click) -> None:
        # Mouse users get the same skip affordance as keyboard users.
        event.stop()
        self._auto_dismiss()

    def _auto_dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        # Stop our timers eagerly — Textual auto-cancels on unmount, but
        # an in-flight tick mid-pop_screen could still race with widget
        # teardown and produce a "no such widget" warning in the log.
        self._stop_timer("_typewriter_timer")
        self._stop_timer("_underline_timer")
        self._stop_timer("_breath_timer")
        self._stop_timer("_logo_timer")
        try:
            self.app.pop_screen()
        except Exception:  # pragma: no cover - defensive
            pass
        # ``on_done`` fires AFTER the pop so the callback runs against
        # the now-active main screen (e.g. for kicking a resize event).
        if self._on_done is not None:
            try:
                self._on_done()
            except Exception:  # pragma: no cover
                pass


__all__ = ["SplashScreen"]
