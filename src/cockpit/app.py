"""Textual cockpit application."""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Input, Static

from . import data
from .bars import progress_bar
from .commands import CockpitCommands, ThemeSwitcherCommands
from .i18n import normalize_lang, t, toggle_lang
from .layout import (
    LAYOUT_FOCUS,
    LAYOUT_SINGLE,
    LAYOUT_WIDE,
    all_layout_classes,
    css_class_for,
    resolve_for_width,
)
from .modals import ConfirmModal, HelpScreen, PinMetricModal, TextInputModal
from .panes import EventStreamPane, HypothesisTreePane, NodeDetailPane, RightTabsPane
from .row_detail import row_detail
from .screens.splash import SplashScreen
from .screens.welcome import WelcomeScreen
from .settings import (
    CockpitSettings,
    load_settings,
    save_settings,
    should_show_splash,
)
from .theme import (
    ALL_THEMES,
    default_theme_name,
    get_theme,
    next_theme,
    update_theme_vars,
)

FOCUS_ORDER = ("tree", "detail", "events", "tabs")


class StatusBar(Static):
    """Single-line status header."""

    def __init__(self, *, lang: str = "en", theme: str = "claude-warm-dark") -> None:
        super().__init__("")
        self.id = "status-bar"
        self.lang = normalize_lang(lang)
        # Theme name shown next to the language code in the HUD so users have
        # a constant reminder of which theme is active (the T-key notification
        # is transient).
        self.theme_name = theme
        self.current_text = ""
        self._summary = {
            "active_hypotheses": 0,
            "refuted_nodes": 0,
            "pinned_claims": 0,
            "unverified_claims": 0,
            "heldout_budgets": [],
            "risks": 0,
            "latest_event_at": None,
        }
        self._clock = "--:--"

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)
        self._refresh_display()

    def set_language(self, lang: str) -> None:
        self.lang = normalize_lang(lang)
        self._refresh_display()

    def set_theme_name(self, theme: str) -> None:
        self.theme_name = theme
        self._refresh_display()

    def set_summary(self, summary: dict) -> None:
        self._summary = dict(summary)
        self._refresh_display()

    def _tick(self) -> None:
        self._clock = datetime.now().strftime("%H:%M")
        self._refresh_display()

    def _refresh_display(self) -> None:
        # Compact theme tag (drops the "claude-" prefix) so the HUD doesn't
        # bloat. e.g. "claude-warm-dark" -> "warm-dark".
        compact_theme = self.theme_name.removeprefix("claude-") or self.theme_name
        try:
            hud_key = "hud_compact" if self.size.width < 100 else "hud"
        except Exception:  # pragma: no cover - pre-mount path
            hud_key = "hud"
        self.current_text = t(
            self.lang,
            hud_key,
            app=t(self.lang, "app_name"),
            active_hypotheses=self._summary.get("active_hypotheses", 0),
            refuted_nodes=self._summary.get("refuted_nodes", 0),
            pinned_claims=self._summary.get("pinned_claims", 0),
            unverified_claims=self._summary.get("unverified_claims", 0),
            heldout=self._format_heldout(),
            risks=self._summary.get("risks", 0),
            last_event=self._format_last_event(),
            theme=compact_theme,
            lang_code=self.lang.upper(),
            clock=self._clock,
        )
        self.update(self.current_text)

    def _format_heldout(self) -> str:
        budgets = self._summary.get("heldout_budgets") or []
        if not budgets:
            return t(self.lang, "heldout_none")
        # Compact bar (6 cells) keeps the HUD honest on narrow terminals
        # while still giving a real fill cue. Two datasets max — anything
        # beyond that belongs in the risks tab, not the status bar.
        parts: list[str] = []
        for row in budgets[:2]:
            used = int(row.get("budget_used", 0) or 0)
            total = int(row.get("budget_total", 0) or 0)
            bar = progress_bar(used, total, width=6)
            parts.append(f"{row.get('dataset', '-')} {bar} {used}/{total}")
        return ", ".join(parts)

    def _format_last_event(self) -> str:
        raw = self._summary.get("latest_event_at")
        if not raw:
            # Hollow dot conveys "no signal yet" without alarming the user.
            return f"○ {t(self.lang, 'last_never')}"
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return f"● {str(raw)[:8]}"
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        seconds = max(int(delta.total_seconds()), 0)
        # Filled dot for fresh events (< 2s) so the user gets a low-effort
        # "system is alive" cue in their peripheral vision; we drop to a
        # hollow ring once the trail goes cold.
        dot = "●" if seconds < 2 else "○"
        if seconds < 5:
            return f"{dot} {t(self.lang, 'just_now')}"
        if seconds < 60:
            return f"{dot} {t(self.lang, 'seconds_ago', value=seconds)}"
        minutes = seconds // 60
        if minutes < 60:
            return f"{dot} {t(self.lang, 'minutes_ago', value=minutes)}"
        return f"{dot} {t(self.lang, 'hours_ago', value=minutes // 60)}"


class ContextBar(Static):
    """Localized one-line hint for the focused pane."""

    def __init__(self, *, lang: str = "en") -> None:
        super().__init__("")
        self.id = "context-bar"
        self.lang = normalize_lang(lang)
        self.pane = "tree"
        self.current_text = ""
        self.refresh_text()

    def set_language(self, lang: str) -> None:
        self.lang = normalize_lang(lang)
        self.refresh_text()

    def set_pane(self, pane: str) -> None:
        self.pane = pane
        self.refresh_text()

    def refresh_text(self) -> None:
        key = {
            "tree": "context_tree",
            "tabs": "context_tabs",
            "events": "context_events",
            "detail": "context_detail",
        }.get(self.pane, "context_tree")
        self.current_text = t(self.lang, key)
        self.update(self.current_text)


class CockpitApp(App[None]):
    """Textual-based cockpit for live research state."""

    CSS_PATH = str(Path(__file__).with_name("theme").joinpath("cockpit.tcss"))

    # The system command palette (Ctrl+P) merges these providers with
    # Textual's built-ins. Custom providers are listed first so cockpit
    # actions outrank the default app-quit / theme-cycle entries.
    COMMANDS = App.COMMANDS | {CockpitCommands, ThemeSwitcherCommands}
    BINDINGS = [
        Binding("1", "focus_tree", "Tree"),
        Binding("2", "focus_detail", "Detail"),
        Binding("3", "focus_events", "Events"),
        Binding("4", "focus_tabs", "Tabs"),
        # priority=True so Tab fires the cockpit-wide pane cycle even
        # when a DataTable / Input has focus. Without priority, Textual's
        # default "focus next focusable child" handler swallows the key
        # inside the tabs pane and the user gets stuck (regression caught
        # by test_tab_from_tabs_pane_advances_focus_to_tree).
        Binding("tab", "focus_next_pane", "Next Pane", priority=True),
        Binding("shift+tab", "focus_prev_pane", "Prev Pane", priority=True),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
        Binding("h", "pane_left", "Left"),
        Binding("l", "pane_right", "Right"),
        Binding("g", "jump_top", "Top"),
        Binding("G", "jump_bottom", "Bottom"),
        Binding("f", "cycle_right_tab", "Cycle Tab"),
        # Capital N jumps to the first tab of the next group
        # (Cross → Empirical → Proof → Cross). priority=True so a
        # focused DataTable doesn't swallow it; the priority-letter
        # forwarder lets the user still type literal "N" inside a
        # modal Input.
        Binding("N", "cycle_tab_group", "Next Tab Group", priority=True),
        # priority=True so Tree / DataTable can't swallow Enter. The Tree
        # widget binds Enter to "select_cursor" by default (and the
        # DataTable / Input behave similarly); without priority the
        # cockpit-wide drill never fires from those panes.
        Binding("enter", "drill_selection", "Open", priority=True),
        Binding("y", "approve_node", "Approve"),
        Binding("n", "reject_node", "Reject"),
        Binding("r", "redirect_node", "Redirect"),
        Binding("c", "constrain_node", "Constrain"),
        Binding("m", "mark_refuted", "Refute"),
        Binding("p", "pin_metric", "Pin"),
        # `e` opens the export modal for the currently-selected node.
        # priority=True with the standard Input-yield helper so typing
        # the literal "e" inside a modal text field still works.
        Binding("e", "export_report", "Export", priority=True),
        Binding("H", "halt_agent", "Halt"),
        Binding("/", "open_filter", "Filter"),
        Binding(":", "open_command", "Command"),
        Binding("?", "show_help", "Help"),
        Binding("t", "toggle_timestamp_mode", "Time"),
        Binding("s", "toggle_refuted", "Refuted"),
        # Priority bindings: these meta-actions must fire regardless of
        # which widget has focus. Without priority=True a focused
        # DataTable / Input swallows the keystroke and the user thinks
        # the binding is broken (e.g. settings.focused_pane="tabs"
        # restores DataTable focus on launch and L/T/F seem dead).
        Binding("L", "toggle_language", "Language", priority=True),
        Binding("T", "cycle_theme", "Theme", priority=True),
        Binding("F", "toggle_focus", "Focus", priority=True),
        Binding("R", "force_refresh", "Refresh"),
        Binding("ctrl+l", "clear_event_log", "Clear Events"),
        # v4.1.0a4 display toggles. priority=True so that even when an
        # Input/DataTable has focus the keystroke still fires (matches the
        # L/T/F precedent above).
        # `w` and `i` are pane-scoped (v4.2.0a1 / A3): see
        # EventStreamPane.BINDINGS and HypothesisTreePane.BINDINGS.
        # The App keeps the action handlers (action_toggle_event_wrap /
        # action_toggle_tree_compact) because the panes delegate back
        # to them for the persisted-state side effects; only the keystroke
        # ownership moved.
        # `<` / `>` nudge the wide-layout tree column wider/narrower.
        # Lower-case input convention: shift+comma / shift+period in
        # Textual's key naming. priority so they fire even when an Input
        # has focus (e.g. while the user is in filter mode).
        Binding("less_than_sign", "shrink_tree", "Shrink Tree", priority=True),
        Binding("greater_than_sign", "expand_tree", "Expand Tree", priority=True),
        # Roll back the most recent queued intervention if and only if
        # the agent hasn't consumed it yet (delivered_at IS NULL). After
        # delivery the cockpit must NOT lie that it can rewind history.
        Binding("u", "undo_intervention", "Undo", priority=True),
        Binding("escape", "cancel_context", show=False),
        Binding("q", "quit_requested", "Quit", priority=True),
    ]

    focused_pane = reactive("tree")
    show_refuted = reactive(False)
    relative_timestamps = reactive(False)
    last_event_id = reactive(0)

    def __init__(
        self,
        *,
        lang: str | None = None,
        theme: str | None = None,
        settings: CockpitSettings | None = None,
    ) -> None:
        super().__init__()
        # Settings precedence: explicit kwargs > saved file > built-in defaults.
        # The CLI passes lang/theme as None when the user didn't specify them,
        # so a saved choice from a prior session survives across launches.
        self._settings: CockpitSettings = settings or load_settings()
        if lang is not None:
            self._settings.lang = normalize_lang(lang)
        if theme is not None:
            self._settings.theme = theme
        # Focus/single-pane layout is useful during a session but hostile as a
        # startup default: a prior F-key press can make the next launch look
        # like most panes disappeared. Heal older saved configs immediately.
        if self._settings.layout_preset in (LAYOUT_FOCUS, LAYOUT_SINGLE):
            self._settings.layout_preset = LAYOUT_WIDE
        self.lang = normalize_lang(self._settings.lang)
        self.show_refuted = self._settings.show_refuted
        self.relative_timestamps = self._settings.relative_timestamps
        # Snapshot the saved focused pane BEFORE Textual's reactive system
        # has a chance to fire watch_focused_pane with the default ("tree")
        # during mount and overwrite self._settings.focused_pane. on_mount
        # consumes this snapshot to restore the user's last focus.
        saved_focus = self._settings.focused_pane
        self._initial_focus = saved_focus if saved_focus in FOCUS_ORDER else "tree"
        self._pre_focus_preset = self._settings.layout_preset or LAYOUT_WIDE
        self.graph = data.GraphSnapshot(nodes={})
        self.selected_node_id: str | None = None
        self._command_mode: str | None = None
        self._command_target = "tree"
        self._pane_filters = {"tree": "", "events": "", "tabs": ""}
        # Per-mode draft buffers for the bottom Input. The user can start
        # typing a `:` command, get distracted, press Esc, and the next `:`
        # restores their half-typed text. Filter mode is intentionally NOT
        # buffered here — its draft is the active filter (in _pane_filters)
        # and is restored from there.
        self._command_buffer: str = ""
        # Most recent intervention id for the `u` undo path. Set by
        # _notify_intervention_queued; cleared on successful undo. Holds
        # only the id from the *current* session — restarting the cockpit
        # forfeits undo, which is the correct safety property: a stale id
        # could collide with a future row.
        self._last_intervention_id: int | None = None
        self._last_intervention_kind: str | None = None
        self._last_intervention_target: str | None = None
        self._detail_override = False
        self._stop_event_worker = False

    def compose(self) -> ComposeResult:
        yield StatusBar(lang=self.lang, theme=self._settings.theme)
        # Compose order is load-bearing for the grid auto-flow.
        #
        # Textual's grid placement is row-major (left-to-right, then next row),
        # filling the next free cell in compose order. With Tree row-span=2
        # (wide) / =3 (narrow), Tree consumes column 1 entirely; subsequent
        # widgets flow row-by-row across the remaining columns.
        #
        # In the wide preset (3 cols × 2 rows) we want
        #     Tree | Detail / Tabs stacked | Events spanning full height.
        # That requires Events placed BEFORE Tabs in compose order so it
        # lands at (col=3,row=1) and its row-span=2 reaches (col=3,row=2).
        # If Tabs went first, it would steal (col=3,row=1) and Events would
        # fall to (col=2,row=2) leaving (col=3,row=2) blank.
        #
        # In the narrow preset (2 cols × 3 rows) the same order yields
        #     Tree | Detail / Events / Tabs stacked
        # which keeps the most-frequently-changing pane (Events) right next
        # to Detail and pushes the read-mostly Tabs to the bottom of the
        # right column — also fine.
        with Container(id="body-grid", classes="layout-wide"):
            yield HypothesisTreePane(compact=self._settings.tree_compact)
            yield NodeDetailPane()
            yield EventStreamPane(wrap=self._settings.event_wrap)
            yield RightTabsPane()
        yield Input(placeholder="command", id="command-line", classes="hidden")
        yield ContextBar(lang=self.lang)

    def on_mount(self) -> None:
        self._register_themes()
        self._apply_theme(self._settings.theme, persist=False, notify=False)
        self._apply_language()
        # Wire the detail pane's section-collapse persistence. The pane
        # owns the visual toggle; the App owns the settings file.
        try:
            self.detail_pane.set_section_collapsed_state(
                dict(self._settings.detail_section_collapsed)
            )
            self.detail_pane.set_section_toggle_callback(
                self._on_detail_section_toggled
            )
        except Exception:  # pragma: no cover - defensive
            pass
        self.refresh_state(include_events=True)
        # Restore focus to the previously active pane. tree / detail /
        # events are plain widgets; calling .focus() synchronously is
        # safe and keeps key bindings working from the first keystroke
        # (matching the v4.1.0a0 behaviour).
        #
        # 'tabs' is intentionally NOT restored automatically. The inner
        # DataTable inside RightTabsPane (a TabbedContent subclass) can't
        # be focused programmatically during on_mount: Textual's
        # ContentTabs / ContentSwitcher wrappers are auto-injected lazily
        # and not on the DOM yet, so the bubbled Focused event crashes
        # _watch_active with NoMatches. We could defer to call_after_refresh
        # but the wrappers still aren't ready by the next tick, so the
        # safest path is to downgrade the saved 'tabs' focus to 'tree'
        # at boot and let the user press '4' to re-focus tabs.
        focus_pane = self._initial_focus
        if focus_pane == "tabs":
            focus_pane = "tree"
        self._set_focus(focus_pane)
        self._apply_layout(persist=False)
        self.events_worker()
        # Cold-start Welcome (v4.2.0a3 / B2). Pushed after the main UI
        # is composed but before the splash, so the splash dismisses
        # onto the Welcome screen rather than the bare cockpit.
        # ``RESEARCH_AGENT_COCKPIT_WELCOME=0`` mirrors the splash env
        # var so tests can suppress it without touching settings.
        if self._should_show_welcome():
            try:
                self.push_screen(
                    WelcomeScreen(
                        lang=self.lang,
                        quickstart_path=self._quickstart_doc_path(),
                        on_done=self._mark_welcome_seen,
                    )
                )
            except Exception:  # pragma: no cover - defensive
                pass

        # Splash is pushed LAST so the main view is fully composed,
        # themed, and event-pumped behind it. Popping the splash then
        # reveals an already-warm UI rather than a half-rendered one.
        # Disabled paths (env var / saved preference / reduced motion
        # combined with the env var) skip this entirely.
        if should_show_splash(self._settings):
            try:
                self.push_screen(
                    SplashScreen(
                        lang=self.lang,
                        reduced_motion=self._settings.reduced_motion,
                    )
                )
            except Exception:  # pragma: no cover - splash must never block boot
                pass

    def on_resize(self, event: events.Resize) -> None:  # noqa: ARG002
        # Re-evaluate the active layout whenever the terminal resizes. The
        # saved preset is preserved; only the *resolved* class on body-grid
        # changes (e.g. wide → narrow when the user shrinks the window).
        if self.is_mounted:
            self._apply_layout(persist=False)

    def on_unmount(self) -> None:
        self._stop_event_worker = True
        self._persist_settings()

    # -- theme machinery ---------------------------------------------------

    def _register_themes(self) -> None:
        """Register all bundled themes with Textual's theme system.

        Idempotent: re-registering the same name is a no-op in modern
        Textual. We narrowly catch ``AttributeError`` (older Textual
        without ``register_theme``) and ``TypeError`` (signature drift
        across versions); other exceptions still propagate so real bugs
        surface during development. The static fallback color table in
        tokens.py keeps things readable even if registration fails.
        """
        for theme in ALL_THEMES:
            try:
                self.register_theme(theme)
            except (AttributeError, TypeError):  # pragma: no cover
                pass

    def _apply_theme(self, name: str, *, persist: bool, notify: bool) -> None:
        """Switch the active theme and refresh widgets that compose Rich
        Text styles dynamically (event stream, tree prefixes, detail header).

        If ``name`` is unknown (e.g. settings.toml was hand-edited), we
        silently fall back to the default theme. ``self._settings.theme``
        is then rewritten to the resolved name so the bad value doesn't
        survive — next launch starts cleanly.
        """
        theme = get_theme(name)
        fallback_used = False
        if theme is None:
            theme = get_theme(default_theme_name())
            fallback_used = True
        if theme is None:  # pragma: no cover - default theme should always exist
            return
        # Update the in-process token cache so render code in panes resolves
        # to the new colors on the very next paint.
        update_theme_vars(theme)
        try:
            self.theme = theme.name
        except (AttributeError, TypeError):  # pragma: no cover - older Textual
            pass
        # Heal a corrupted theme name in settings: write the resolved name
        # back so a subsequent quit doesn't re-persist garbage.
        if fallback_used and persist is False:
            persist = True
        self._settings.theme = theme.name
        if persist:
            self._persist_settings()
        if notify:
            label = t(self.lang, f"theme_{theme.name}")
            self.notify(t(self.lang, "theme_changed", name=label))
        # Re-render any pane that builds Rich Text styles outside TCSS.
        if self.is_mounted:
            self.status_bar.set_theme_name(theme.name)
            self._refresh_detail()
            # Tree label styles are baked at load time; reload to pick up the
            # new kind colors.
            self.selected_node_id = self.tree_pane.load_graph(
                self.graph,
                show_refuted=self.show_refuted,
                filter_text=self._pane_filters["tree"],
                selected_node_id=self.selected_node_id,
            )

    def action_cycle_theme(self) -> None:
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input("T"):
            return
        self._apply_theme(next_theme(self._settings.theme), persist=True, notify=True)

    # -- layout machinery --------------------------------------------------

    def _body_grid(self) -> Container:
        return self.query_one("#body-grid", Container)

    _WIDE_SUBPRESET_CLASSES: tuple[str, ...] = ("tree-narrow", "tree-wide")

    def _apply_layout(self, *, persist: bool) -> None:
        """Resolve the saved preset against the current terminal width and
        update the ``#body-grid`` class so the TCSS rules take effect.

        In single (focus) mode, also tag the active pane with
        ``layout-active`` so it is the lone visible pane.
        """
        if not self.is_mounted:
            return
        try:
            width = self.size.width
        except Exception:  # pragma: no cover - pre-mount path
            width = 120
        active = resolve_for_width(self._settings.layout_preset, width)
        target_class = css_class_for(active)
        grid = self._body_grid()
        for cls in all_layout_classes():
            grid.remove_class(cls)
        grid.add_class(target_class)
        # Wide-layout subpreset: tree-narrow (-1) / default (0) / tree-wide (+1).
        # Always strip both modifiers first, then add at most one. The
        # narrow / single layouts ignore the subpreset — it's wide-only.
        for cls in self._WIDE_SUBPRESET_CLASSES:
            grid.remove_class(cls)
        if active == "wide":
            sub = max(-1, min(1, int(self._settings.wide_subpreset)))
            if sub == -1:
                grid.add_class("tree-narrow")
            elif sub == 1:
                grid.add_class("tree-wide")
        # Manage layout-active class on panes for single-pane focus mode.
        panes = {
            "tree": self.tree_pane,
            "detail": self.detail_pane,
            "events": self.events_pane,
            "tabs": self.tabs_pane,
        }
        for name, widget in panes.items():
            if active == "single" and name == self.focused_pane:
                widget.add_class("layout-active")
            else:
                widget.remove_class("layout-active")
        if persist:
            self._persist_settings()

    def action_undo_intervention(self) -> None:
        """Roll back the most recent queued intervention if the hook has
        not yet delivered it. Refuse silently with a toast otherwise.

        See ``data.undo_intervention`` for the SQL contract; the cockpit
        is the only user interface to that function.
        """
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input("u"):
            return
        intervention_id = self._last_intervention_id
        if intervention_id is None:
            self.notify(t(self.lang, "undo_nothing"), severity="warning")
            return
        result = data.undo_intervention(intervention_id)
        if result.get("ok"):
            kind = self._last_intervention_kind or "intervention"
            target = self._last_intervention_target
            self._last_intervention_id = None
            self._last_intervention_kind = None
            self._last_intervention_target = None
            display = self._short_node_label(target) if target else ""
            if display:
                msg = t(self.lang, "undo_done", kind=kind, target=display)
            else:
                msg = t(self.lang, "undo_done_no_target", kind=kind)
            self.notify(msg)
            self.refresh_state(include_events=True)
            return
        reason = str(result.get("reason"))
        if reason == "already_delivered":
            self.notify(t(self.lang, "undo_too_late"), severity="warning")
        else:
            self.notify(t(self.lang, "undo_nothing"), severity="warning")
        # Pointer is no longer useful — clear so a follow-up `u` doesn't
        # produce the same misleading toast.
        self._last_intervention_id = None
        self._last_intervention_kind = None
        self._last_intervention_target = None

    def action_shrink_tree(self) -> None:
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input("<"):
            return
        self._nudge_wide_subpreset(-1)

    def action_expand_tree(self) -> None:
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input(">"):
            return
        self._nudge_wide_subpreset(+1)

    def _nudge_wide_subpreset(self, delta: int) -> None:
        """Step the wide-layout tree column wider (+1) or narrower (-1).

        The subpreset only takes effect under the wide layout — narrow /
        single ignore it (Textual collapses the grid to 2 or 1 columns).
        Keystrokes outside wide warn the user instead of silently storing
        a setting they can't see take effect.
        """
        if not self.is_mounted:
            return
        try:
            width = self.size.width
        except Exception:  # pragma: no cover
            width = 120
        active = resolve_for_width(self._settings.layout_preset, width)
        if active != "wide":
            self.notify(t(self.lang, "wide_only_hint"), severity="warning")
            return
        current = max(-1, min(1, int(self._settings.wide_subpreset)))
        target = max(-1, min(1, current + delta))
        if target == current:
            # Already at the end of the range — toast briefly so the user
            # knows the keystroke registered but had nowhere to go.
            self.notify(t(self.lang, "tree_width_at_limit"))
            return
        self._settings.wide_subpreset = target
        self._apply_layout(persist=True)
        label = {-1: "tree_width_narrow", 0: "tree_width_default", 1: "tree_width_wide"}[
            target
        ]
        self.notify(t(self.lang, label))

    def action_toggle_focus(self) -> None:
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input("F"):
            return
        self._toggle_focus_impl()

    def _toggle_focus_impl(self) -> None:
        """Toggle single-pane focus mode. Preserves the user's prior layout
        preset so exiting focus mode returns to wide / narrow / whatever
        they had instead of always snapping to wide.

        The focus state itself is intentionally session-only; persisting it
        made the next real launch look like Detail / Events / Tabs vanished.
        """
        if self._settings.layout_preset == LAYOUT_FOCUS:
            # Exit focus → restore the preset that was active before we
            # entered focus mode. Fallback to wide if we somehow lost it.
            restored = getattr(self, "_pre_focus_preset", LAYOUT_WIDE) or LAYOUT_WIDE
            self._settings.layout_preset = restored
        else:
            # Enter focus → remember what we're leaving so we can restore.
            self._pre_focus_preset = self._settings.layout_preset
            self._settings.layout_preset = LAYOUT_FOCUS
        self._apply_layout(persist=True)

    # -- settings persistence ---------------------------------------------

    def _should_show_welcome(self) -> bool:
        """True when the cockpit should push the cold-start Welcome screen.

        Skipped when the env var ``RESEARCH_AGENT_COCKPIT_WELCOME=0``
        is set (tests + power users), when the settings file says the
        user has already dismissed it once, or when the SQLite
        ``mem_nodes`` table is non-empty (a warm session).
        """
        import os
        import sqlite3

        if os.environ.get("RESEARCH_AGENT_COCKPIT_WELCOME") == "0":
            return False
        if getattr(self._settings, "welcome_shown", False):
            return False
        try:
            from claudescientist.runtime import (
                connect_existing_sqlite,
                state_db_path,
            )

            con = connect_existing_sqlite(state_db_path())
            if con is None:
                return True
            try:
                row = con.execute(
                    "SELECT COUNT(*) AS n FROM mem_nodes"
                ).fetchone()
                return int(row[0]) == 0
            except sqlite3.OperationalError:
                return True
            finally:
                con.close()
        except Exception:  # pragma: no cover - defensive
            return True

    def _quickstart_doc_path(self):
        from pathlib import Path

        # Resolve relative to the running cwd. The wizard wrote the
        # same path into its cheatsheet, so users get a consistent
        # experience whether they pressed ``?`` here or "Y" at the
        # end of setup.
        return (Path.cwd() / "docs" / "workflows" / "first-research-task.md").resolve()

    def _mark_welcome_seen(self) -> None:
        try:
            self._settings.welcome_shown = True
            self._persist_settings()
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_detail_section_toggled(self, section_key: str, collapsed: bool) -> None:
        """Persist the user's collapse/expand action on a detail section.

        Updates ``CockpitSettings.detail_section_collapsed`` in place and
        flushes to disk. Failures here never bubble up — the visual
        change has already happened.
        """
        try:
            state = dict(self._settings.detail_section_collapsed or {})
            state[section_key] = bool(collapsed)
            self._settings.detail_section_collapsed = state
            self._persist_settings()
        except Exception:  # pragma: no cover - defensive
            pass

    def _persist_settings(self) -> None:
        """Write the current settings snapshot to disk. Swallows OSError so
        a hostile filesystem (read-only, missing parent, etc.) cannot crash
        the cockpit at quit time."""
        self._settings.lang = self.lang
        self._settings.show_refuted = bool(self.show_refuted)
        self._settings.relative_timestamps = bool(self.relative_timestamps)
        settings_to_save = self._settings
        if self._settings.layout_preset in (LAYOUT_FOCUS, LAYOUT_SINGLE):
            settings_to_save = replace(
                self._settings,
                layout_preset=getattr(self, "_pre_focus_preset", LAYOUT_WIDE)
                or LAYOUT_WIDE,
            )
        try:
            save_settings(settings_to_save)
        except OSError:
            pass

    @property
    def status_bar(self) -> StatusBar:
        return self.query_one(StatusBar)

    @property
    def tree_pane(self) -> HypothesisTreePane:
        return self.query_one(HypothesisTreePane)

    @property
    def detail_pane(self) -> NodeDetailPane:
        return self.query_one(NodeDetailPane)

    @property
    def events_pane(self) -> EventStreamPane:
        return self.query_one(EventStreamPane)

    @property
    def tabs_pane(self) -> RightTabsPane:
        return self.query_one(RightTabsPane)

    @property
    def command_line(self) -> Input:
        return self.query_one("#command-line", Input)

    @property
    def context_bar(self) -> ContextBar:
        return self.query_one(ContextBar)

    def refresh_state(self, *, include_events: bool) -> None:
        self._refresh_graph()
        self._refresh_tabs()
        self._refresh_counts()
        if include_events:
            self._refresh_events()
        self._detail_override = False
        self.detail_pane.clear_override()
        self._refresh_detail()
        # If a DetailScreen is on top of the stack, repaint it so action
        # keys (y/n/r/c/m) fired from inside the drill-in surface their
        # state change immediately — without this the user sees a stale
        # node body and has to bounce out and back in.
        self._repaint_top_detail_screen()

    def _repaint_top_detail_screen(self) -> None:
        if len(self.screen_stack) <= 1:
            return
        try:
            from .screens import DetailScreen as _Detail

            top = self.screen_stack[-1]
            if isinstance(top, _Detail):
                top.set_language(self.lang)
                top.refresh_content()
        except Exception:  # pragma: no cover - defensive
            pass

    def watch_focused_pane(self, _old: str, new: str) -> None:
        panes = {
            "tree": self.tree_pane,
            "detail": self.detail_pane,
            "events": self.events_pane,
            "tabs": self.tabs_pane,
        }
        for name, widget in panes.items():
            if name == new:
                widget.add_class("pane-active")
            else:
                widget.remove_class("pane-active")
        self.context_bar.set_pane(new)
        # Persist the new focus + refresh layout-active class so single-pane
        # focus mode swaps to the newly focused pane immediately. Persist to
        # disk too so the next launch restores the same focused pane (only
        # while mounted — the watcher fires once during mount before
        # _persist_settings could find a config dir, which is safe to skip).
        self._settings.focused_pane = new
        if self.is_mounted:
            self._apply_layout(persist=False)
            self._persist_settings()

    def on_tree_node_selected(self, event: HypothesisTreePane.NodeSelected) -> None:
        node_id = event.node.data if isinstance(event.node.data, str) else None
        self.selected_node_id = node_id
        self._detail_override = False
        self.detail_pane.clear_override()
        self._refresh_detail()

    def on_data_table_row_highlighted(self, _event) -> None:
        if self.focused_pane == "tabs":
            self._detail_override = False
            self.detail_pane.clear_override()
            self._refresh_detail()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-line":
            return
        value = event.value.strip()
        mode = self._command_mode
        target = self._command_target
        self._hide_command_line()
        if mode == "command":
            # The draft was committed — clear the per-app buffer so the
            # next `:` opens to an empty input, not a stale command.
            self._command_buffer = ""
            self._execute_command(value)
            return
        if mode == "filter":
            self._apply_filter(target, value)
            self._refresh_detail()

    def on_key(self, event) -> None:
        if event.key == "escape" and not self.command_line.has_class("hidden"):
            self._hide_command_line(clear_filter=self._command_mode == "filter")
            event.stop()

    def action_focus_tree(self) -> None:
        self._set_focus("tree")

    def action_focus_detail(self) -> None:
        self._set_focus("detail")

    def action_focus_events(self) -> None:
        self._set_focus("events")

    def action_focus_tabs(self) -> None:
        self._set_focus("tabs")

    def action_focus_next_pane(self) -> None:
        # Priority Tab on the App swallows the keystroke before it reaches
        # any focused widget — including the inputs inside PinMetricModal
        # / TextInputModal, which rely on Tab → focus_next() to walk their
        # fields. When a modal is on the stack we forward the operation
        # to the modal so its own field cycle still works.
        if len(self.screen_stack) > 1:
            top = self.screen_stack[-1]
            try:
                top.focus_next()
            except Exception:  # pragma: no cover - defensive
                pass
            return
        index = FOCUS_ORDER.index(self.focused_pane)
        self._set_focus(FOCUS_ORDER[(index + 1) % len(FOCUS_ORDER)])

    def action_focus_prev_pane(self) -> None:
        if len(self.screen_stack) > 1:
            top = self.screen_stack[-1]
            try:
                top.focus_previous()
            except Exception:  # pragma: no cover - defensive
                pass
            return
        index = FOCUS_ORDER.index(self.focused_pane)
        self._set_focus(FOCUS_ORDER[(index - 1) % len(FOCUS_ORDER)])

    def action_cursor_down(self) -> None:
        if self.focused_pane == "tree":
            self.tree_pane.move_cursor_by(1)
            self.selected_node_id = self.tree_pane.current_node_id()
        elif self.focused_pane == "tabs":
            self.tabs_pane.move_cursor_by(1)
        self._refresh_detail()

    def action_cursor_up(self) -> None:
        if self.focused_pane == "tree":
            self.tree_pane.move_cursor_by(-1)
            self.selected_node_id = self.tree_pane.current_node_id()
        elif self.focused_pane == "tabs":
            self.tabs_pane.move_cursor_by(-1)
        self._refresh_detail()

    def action_pane_left(self) -> None:
        if self.focused_pane == "tree":
            self.tree_pane.collapse_current()
            return
        self.action_focus_prev_pane()

    def action_pane_right(self) -> None:
        if self.focused_pane == "tree":
            self.tree_pane.expand_current()
            return
        self.action_focus_next_pane()

    def action_jump_top(self) -> None:
        if self.focused_pane == "tree":
            self.tree_pane.move_cursor_to_top()
            self.selected_node_id = self.tree_pane.current_node_id()
        elif self.focused_pane == "tabs":
            self.tabs_pane.move_cursor_to_top()
        self._refresh_detail()

    def action_jump_bottom(self) -> None:
        if self.focused_pane == "tree":
            self.tree_pane.move_cursor_to_bottom()
            self.selected_node_id = self.tree_pane.current_node_id()
        elif self.focused_pane == "tabs":
            self.tabs_pane.move_cursor_to_bottom()
        self._refresh_detail()

    def action_cycle_right_tab(self) -> None:
        self.tabs_pane.cycle_tab()
        self._refresh_detail()

    async def action_export_report(self) -> None:
        """Open the ExportModal for the currently-selected node.

        Skipped silently if focus is in an Input — the modal's `e`
        would otherwise eat literal typing inside a filter field. The
        modal returns an ExportRequest on submit; we then call into
        cockpit.export.generate to write the file(s) and notify the
        user with the paths.
        """
        if self._yield_priority_letter_to_input("e"):
            return
        node_id = self.selected_node_id
        if not node_id:
            self.notify(t(self.lang, "select_hint"))
            return
        # Look up the node's kind so the modal only offers report
        # kinds that make sense.
        node = self.graph.node(node_id) if self.graph else None
        if node is None:
            self.notify(t(self.lang, "select_hint"))
            return
        from cockpit.export.pipeline import kinds_for_node_kind
        from cockpit.modals import ExportModal, ExportRequest

        kinds = kinds_for_node_kind(node.kind)

        async def _on_dismiss(result: ExportRequest | None) -> None:
            if result is None:
                return
            try:
                from cockpit.export import generate

                paths = generate(
                    result.kind,
                    node_id,
                    formats=result.formats,
                    generated_by="cockpit.tui",
                )
            except (ValueError, OSError) as exc:
                self.notify(t(self.lang, "export_failure", error=str(exc)))
                return
            self.notify(t(self.lang, "export_success", count=len(paths)))

        self.push_screen(
            ExportModal(node_id, kinds, lang=self.lang), _on_dismiss
        )

    def action_cycle_tab_group(self) -> None:
        """Jump to the first tab of the next group (Cross → Empirical → Proof)."""
        # Same priority-letter forwarding trick as the other capital
        # bindings: if focus is in an Input widget, the user is typing
        # literal "N" rather than asking for the group cycle.
        if self._yield_priority_letter_to_input("N"):
            return
        self.tabs_pane.cycle_group()
        self._refresh_detail()

    def action_show_help(self) -> None:
        sections = [
            (
                t(self.lang, "help_navigation"),
                [
                    ("j / k", t(self.lang, "move_selection")),
                    ("h / l", t(self.lang, "collapse_expand")),
                    ("1-4", t(self.lang, "jump_pane")),
                    ("Tab", t(self.lang, "cycle_panes")),
                    ("f", t(self.lang, "cycle_tab_in_group")),
                    ("N", t(self.lang, "cycle_tab_group")),
                ],
            ),
            (
                t(self.lang, "help_actions"),
                [
                    ("y / n", t(self.lang, "approve_reject")),
                    ("r / c", t(self.lang, "redirect_constrain")),
                    ("m", t(self.lang, "mark_refuted")),
                    ("p", t(self.lang, "pin_metric")),
                    ("H", t(self.lang, "halt_agent")),
                ],
            ),
            (
                t(self.lang, "help_meta"),
                [
                    ("/", t(self.lang, "filter")),
                    (":", t(self.lang, "command_mode")),
                    ("t", t(self.lang, "toggle_time")),
                    ("s", t(self.lang, "toggle_refuted")),
                    ("L", t(self.lang, "toggle_language")),
                    ("T", t(self.lang, "cycle_theme")),
                    ("q", t(self.lang, "quit")),
                ],
            ),
        ]
        self.push_screen(HelpScreen(sections, self.lang))

    def action_open_command(self) -> None:
        self._show_command_line("command", t(self.lang, "command_placeholder"))

    def action_open_filter(self) -> None:
        target = self.focused_pane if self.focused_pane in {"tree", "events", "tabs"} else "tree"
        placeholder = {
            "tree": t(self.lang, "filter_tree"),
            "events": t(self.lang, "filter_events"),
            "tabs": t(self.lang, "filter_tabs"),
        }[target]
        self._show_command_line("filter", placeholder, target=target)

    def action_toggle_language(self) -> None:
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input("L"):
            return
        self.lang = toggle_lang(self.lang)
        # Keep settings.lang in lockstep so a hard kill before on_unmount
        # still preserves the choice. _persist_settings() is the single
        # source of truth for both syncing and writing to disk.
        self._apply_language()
        self.refresh_state(include_events=True)
        self.notify(t(self.lang, "language_notice"))
        self._persist_settings()

    def action_toggle_timestamp_mode(self) -> None:
        self.relative_timestamps = not self.relative_timestamps
        self.events_pane.set_relative_timestamps(self.relative_timestamps)
        self._persist_settings()

    def _yield_priority_letter_to_input(self, literal: str) -> bool:
        """Forward a priority-bound literal keystroke to a focused Input.

        Priority bindings on the App fire before the focused widget gets
        the key, so without this helper the user typing 'L' / 'T' / 'F'
        / 'w' / 'i' / 'u' / '<' / '>' inside a modal Input would get the
        toggle action instead of the literal character. We detect Input
        focus, insert the character at the cursor, and tell the caller to skip its
        normal action body.

        Returns True when the keystroke was forwarded (caller should
        return immediately); False when no Input is focused (caller
        should run its normal action).
        """
        focused = self.focused
        if isinstance(focused, Input):
            try:
                focused.insert_text_at_cursor(literal)
            except Exception:  # pragma: no cover - defensive
                pass
            return True
        return False

    def _priority_action_blocked_by_help(self) -> bool:
        """Keep overlays (Help, Splash) as real shields for App-level
        priority bindings.

        Without this, App.BINDINGS with ``priority=True`` (T/L/F/y/n/...)
        fire even while the user is on a help or splash screen — meaning
        ``T`` during the launch animation would silently cycle the theme
        of the half-mounted main view behind the splash, etc. The name
        is preserved for backward compatibility (extensive call sites);
        in practice it gates against both overlays.
        """
        if len(self.screen_stack) <= 1:
            return False
        try:
            top = self.screen_stack[-1]
            return isinstance(top, (HelpScreen, SplashScreen, WelcomeScreen))
        except Exception:  # pragma: no cover - defensive
            return False

    def action_toggle_event_wrap(self) -> None:
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input("w"):
            return
        new_state = not self._settings.event_wrap
        self._settings.event_wrap = new_state
        self.events_pane.set_wrap(new_state)
        self.notify(
            t(self.lang, "event_wrap_on" if new_state else "event_wrap_off")
        )
        self._persist_settings()

    def action_toggle_tree_compact(self) -> None:
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input("i"):
            return
        new_state = not self._settings.tree_compact
        self._settings.tree_compact = new_state
        self.tree_pane.set_compact(new_state)
        # Reload labels so the BT/Elo suffix appears or disappears
        # immediately. We pass the cached graph + current filter through
        # the canonical entry point so node selection is preserved.
        self.selected_node_id = self.tree_pane.load_graph(
            self.graph,
            show_refuted=self.show_refuted,
            filter_text=self._pane_filters["tree"],
            selected_node_id=self.selected_node_id,
        )
        self.notify(
            t(self.lang, "tree_compact_on" if new_state else "tree_compact_off")
        )
        self._persist_settings()

    def action_toggle_refuted(self) -> None:
        self.show_refuted = not self.show_refuted
        self.selected_node_id = self.tree_pane.load_graph(
            self.graph,
            show_refuted=self.show_refuted,
            filter_text=self._pane_filters["tree"],
            selected_node_id=self.selected_node_id,
        )
        self._refresh_detail()
        self._persist_settings()

    def action_force_refresh(self) -> None:
        self.refresh_state(include_events=True)

    def action_clear_event_log(self) -> None:
        self.events_pane.clear_visual()

    def action_cancel_context(self) -> None:
        if not self.command_line.has_class("hidden"):
            self._hide_command_line(clear_filter=self._command_mode == "filter")
            return
        if self._detail_override:
            self._detail_override = False
            self.detail_pane.clear_override()
            self._refresh_detail()

    def action_quit_requested(self) -> None:
        if self._priority_action_blocked_by_help():
            return
        if self._yield_priority_letter_to_input("q"):
            return
        # When a Screen is pushed (DetailScreen, modals), `q` should pop
        # back to the main screen — exiting the entire app from inside a
        # drill-in is jarring and easy to trigger by accident. Modals
        # already register their own escape paths (PinMetricModal / Help
        # use Esc), so this fallback only kicks in for screens that don't
        # bind q themselves. The main-screen invariant — q exits — is
        # preserved by checking screen_stack length.
        if len(self.screen_stack) > 1:
            self.pop_screen()
            return
        self.exit()

    def action_approve_node(self) -> None:
        self._queue_intervention("approve")

    def action_reject_node(self) -> None:
        self._queue_intervention("reject")

    def action_redirect_node(self) -> None:
        node_id = self._require_selected_node()
        if node_id is None:
            return
        self.push_screen(
            TextInputModal(t(self.lang, "redirect_title"), t(self.lang, "redirect_prompt")),
            callback=lambda payload, node_id=node_id: self._handle_text_action(
                "redirect", node_id, payload
            ),
        )

    def action_constrain_node(self) -> None:
        node_id = self._require_selected_node()
        if node_id is None:
            return
        self.push_screen(
            TextInputModal(t(self.lang, "constrain_title"), t(self.lang, "constrain_prompt")),
            callback=lambda payload, node_id=node_id: self._handle_text_action(
                "constrain", node_id, payload
            ),
        )

    def action_mark_refuted(self) -> None:
        node_id = self._require_selected_node()
        if node_id is None:
            return
        self.push_screen(
            ConfirmModal(
                t(self.lang, "mark_refuted_title"),
                t(self.lang, "mark_refuted_prompt", node_id=node_id),
                lang=self.lang,
            ),
            callback=lambda confirmed, node_id=node_id: self._handle_mark_refuted(
                node_id, confirmed
            ),
        )

    def action_pin_metric(self) -> None:
        dataset = self.selected_node_id or "session"
        self.push_screen(
            PinMetricModal(dataset=dataset, lang=self.lang),
            callback=self._handle_pin_metric,
        )

    def action_halt_agent(self) -> None:
        self.push_screen(
            ConfirmModal(t(self.lang, "halt_title"), t(self.lang, "halt_prompt"), lang=self.lang),
            callback=self._handle_halt,
        )

    async def action_drill_selection(self) -> None:
        """Push a full-window DetailScreen for the row under focus.

        Branches by focused pane so the same Enter keystroke does the
        right thing wherever the user is reading:
        - tree   → NodeDetailSource over the visible-id list
        - tabs   → TabRowDetailSource over the active subtab's filtered rows
        - events → EventDetailSource over the most recent N events
        - detail → no-op (the user is already in a detail view)

        The DetailScreen keeps the App's ``selected_node_id`` in sync
        when the source is node-backed, so action keys (y/n/r/c/m/p/H)
        keep working without extra wiring.

        Because the Enter binding carries ``priority=True`` (so DataTable
        / Tree don't swallow it on the main screen), this action is also
        responsible for forwarding Enter to the currently-active context
        when drill-in doesn't apply: a modal, the command-line input, or
        a separate Screen (e.g. HelpScreen, DetailScreen itself). Without
        the forwarding, those contexts never see Enter.
        """
        # Forward to the topmost Screen / modal so its own Enter handler
        # (e.g. HelpScreen dismiss on enter, PinMetricModal field cycle)
        # still runs.
        if len(self.screen_stack) > 1:
            top = self.screen_stack[-1]
            # HelpScreen: dismiss on enter (its on_key whitelist).
            try:
                from .modals.help import HelpScreen as _Help

                if isinstance(top, _Help):
                    top.dismiss(None)
                    return
            except Exception:  # pragma: no cover
                pass
            # Inputs inside the modal — submit to fire on_input_submitted.
            try:
                focused = top.focused  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                focused = None
            if focused is not None and hasattr(focused, "action_submit"):
                try:
                    result = focused.action_submit()
                    # Input.action_submit is a coroutine in modern Textual;
                    # await when the call returns one, else assume sync.
                    import inspect as _inspect

                    if _inspect.isawaitable(result):
                        await result
                except Exception:  # pragma: no cover
                    pass
            return
        # Command-line input: submit so on_input_submitted fires the
        # command / filter pipeline. Without this the priority Enter
        # would silently drop the user's command.
        if self.is_mounted and not self.command_line.has_class("hidden"):
            try:
                result = self.command_line.action_submit()
                import inspect as _inspect

                if _inspect.isawaitable(result):
                    await result
            except Exception:  # pragma: no cover
                pass
            return
        # Infer which pane to drill from based on the actually-focused
        # widget, not the ``focused_pane`` reactive. Mouse clicks move the
        # OS focus but don't go through ``_set_focus()``, so the reactive
        # can be stale (e.g. user pressed `3` earlier, then clicked the
        # tree with the mouse — ``focused_pane`` still says "events").
        # Using actual focus lets Enter Just Work regardless of input
        # device. Falls back to the reactive when no widget matches.
        target = self._resolve_drill_pane()
        if target == "tree":
            self._open_detail_for_tree()
        elif target == "tabs":
            self._open_detail_for_tabs()
        elif target == "events":
            self._open_detail_for_events()
        # detail pane drill-in is intentionally a no-op — there is
        # nothing deeper to drill into from a detail view.

    def _resolve_drill_pane(self) -> str:
        """Walk the focus chain back to a known pane, or fall back to the
        reactive. Returns one of "tree" / "tabs" / "events" / "detail".
        """
        try:
            focused = self.focused
        except Exception:  # pragma: no cover - defensive
            focused = None
        widget = focused
        # Cap the walk so a corrupt parent chain can't loop forever.
        for _ in range(32):
            if widget is None:
                break
            try:
                if widget is self.tree_pane:
                    return "tree"
                if widget is self.detail_pane:
                    return "detail"
                if widget is self.events_pane:
                    return "events"
                if widget is self.tabs_pane:
                    return "tabs"
            except Exception:  # pragma: no cover
                break
            widget = getattr(widget, "parent", None)
        return self.focused_pane

    def _open_detail_for_tree(self) -> None:
        node_id = self.tree_pane.current_node_id() or self.selected_node_id
        if node_id is None:
            self.notify(t(self.lang, "no_node"), severity="warning")
            return
        # Guard against a stale cursor pointing at a node that's been
        # evicted from the graph between selection and Enter (rare in
        # single-user use, but possible if the agent refutes / archives
        # while the user is reading). Without this check the DetailScreen
        # would render an empty body and look like the hypothesis vanished.
        if self.graph.node(node_id) is None:
            self.notify(t(self.lang, "no_node"), severity="warning")
            return
        from .screens import DetailScreen, NodeDetailSource

        visible = self.tree_pane.visible_node_ids()
        if not visible:
            return
        # Pass a graph getter (not a snapshot) so action keys mutating
        # the graph from inside the DetailScreen are visible on the next
        # repaint without manual re-push. See _refresh_top_screen().
        source = NodeDetailSource(
            lambda: self.graph, visible, node_id, self.lang
        )
        self.push_screen(DetailScreen(source, lang=self.lang))

    def _open_detail_for_tabs(self) -> None:
        row = self.tabs_pane.current_row()
        if row is None:
            # Active subtab has no real rows (the table is showing the
            # localized "no <kind> yet" placeholder). Stay silent — the
            # placeholder text in the table is already the user-visible
            # answer; an additional toast just stacks up and clutters
            # the screen during exploration.
            return
        # Reports tab gets special-cased: Enter opens the underlying
        # file in the user's default app (the cockpit doesn't embed
        # a markdown / HTML renderer — see ADR 0009). Falling through
        # to the regular drill-in source would only show the metadata
        # we already render in the table.
        active = self.tabs_pane.active or "risks"
        if active == "reports":
            self._open_report_file(row)
            return
        from .screens import DetailScreen, TabRowDetailSource

        # Mirror the rows that tabs_pane shows after filtering — the
        # source must walk only what's visible, not the full backing list.
        rows = self.tabs_pane._filtered_rows.get(active, [])
        try:
            current_idx = rows.index(row)
        except ValueError:
            current_idx = 0
        source = TabRowDetailSource(
            rows, current_idx, self._row_detail, self.lang
        )
        self.push_screen(DetailScreen(source, lang=self.lang))

    def _open_report_file(self, row: dict) -> None:
        """Open a report row's underlying file in the user's default app.

        Honors the ``missing`` flag — if the row points at a file that
        no longer exists on disk (the user manually deleted it), the
        cockpit notifies instead of trying to launch a no-op.
        """
        from pathlib import Path

        from claudescientist._setup_io import open_file_with_default_app

        path_str = row.get("file_path")
        if not path_str or row.get("missing"):
            self.notify(t(self.lang, "reports_missing_flag"))
            return
        opened = open_file_with_default_app(Path(path_str))
        if not opened:
            self.notify(
                t(self.lang, "export_failure", error=f"could not open {path_str}")
            )

    def _open_detail_for_events(self) -> None:
        from .screens import DetailScreen, EventDetailSource

        # Use the most recent events from the events pane's in-memory
        # rows so the source stays consistent with what the user just saw.
        rows = list(reversed(self.events_pane._rows))  # newest first
        if not rows:
            # Same reason as the tabs branch — the events pane already
            # renders "no events yet" inline; an extra toast is noise.
            return
        source = EventDetailSource(rows, 0, self.lang)
        self.push_screen(DetailScreen(source, lang=self.lang))

    @work(exclusive=True)
    async def events_worker(self) -> None:
        while not self._stop_event_worker:
            new_rows = await asyncio.to_thread(data.fetch_new_events, self.last_event_id)
            if new_rows:
                self.events_pane.append_rows(new_rows)
                self.last_event_id = int(new_rows[-1]["id"])
                self._dispatch_events(new_rows)
            await asyncio.sleep(1.0)

    def _set_focus(self, pane_name: str) -> None:
        self.focused_pane = pane_name
        target_map = {
            "tree": lambda: self.tree_pane,
            "detail": lambda: self.detail_pane,
            "events": lambda: self.events_pane,
            "tabs": lambda: self.tabs_pane.current_table(),
        }
        target_factory = target_map.get(pane_name)
        if target_factory is None:
            return
        try:
            target_factory().focus()
        except (NoMatches, AttributeError):
            # The 'tabs' case can hit NoMatches if the user presses '4'
            # before TabbedContent has finished injecting its ContentTabs
            # / ContentSwitcher children (which it does lazily). Reactive
            # state is already updated, so the cockpit stays consistent;
            # the user can press '4' again after a moment and it will
            # work. Better than crashing the whole app.
            pass

    def _apply_language(self) -> None:
        self.status_bar.set_language(self.lang)
        self.context_bar.set_language(self.lang)
        self.tree_pane.set_language(self.lang)
        self.detail_pane.set_language(self.lang)
        self.events_pane.set_language(self.lang)
        self.tabs_pane.set_language(self.lang)
        self.context_bar.set_pane(self.focused_pane)
        self._repaint_top_detail_screen()

    def _show_command_line(self, mode: str, placeholder: str, *, target: str = "tree") -> None:
        self._command_mode = mode
        self._command_target = target
        self.command_line.placeholder = placeholder
        # Filter mode draws its draft from the active filter; command mode
        # restores the per-app draft buffer so a half-typed command isn't
        # lost when the user dismisses with Esc and reopens with `:`.
        if mode == "filter":
            self.command_line.value = self._pane_filters.get(target, "")
        else:
            self.command_line.value = self._command_buffer
        self.command_line.remove_class("hidden")
        self.command_line.focus()
        self.command_line.action_end()

    def _hide_command_line(self, *, clear_filter: bool = False) -> None:
        mode = self._command_mode
        target = self._command_target
        # Stash the current command-mode draft so the next `:` restores it.
        # Filter mode doesn't need stashing — its source of truth is
        # _pane_filters, which the input has been writing through already.
        if mode == "command":
            self._command_buffer = self.command_line.value
        self.command_line.value = ""
        self.command_line.add_class("hidden")
        self._command_mode = None
        if clear_filter and mode == "filter":
            self._apply_filter(target, "")
        self._set_focus(self.focused_pane)

    def _queue_intervention(self, kind: str) -> None:
        node_id = self._require_selected_node()
        if node_id is None:
            return
        result = data.write_intervention(kind, node_id, "")
        self._track_intervention(result, kind, node_id)
        self.refresh_state(include_events=True)

    def _track_intervention(
        self,
        result: dict | None,
        kind: str,
        target: str | None,
    ) -> None:
        """Record the latest intervention for the `u` undo path AND toast.

        ``result`` is the dict returned by ``data.write_intervention`` —
        we read its ``intervention_id`` to seed the undo. For non-queued
        actions (refute/pin) callers pass ``None`` so the undo pointer is
        cleared (those mutations aren't reversible from the cockpit).
        """
        if result and "intervention_id" in result:
            self._last_intervention_id = int(result["intervention_id"])
            self._last_intervention_kind = kind
            self._last_intervention_target = target
        else:
            # Non-undoable action — clear the pointer so the user doesn't
            # press `u` thinking it'll roll back e.g. a refute.
            self._last_intervention_id = None
            self._last_intervention_kind = None
            self._last_intervention_target = None
        self._notify_intervention_queued(kind, target)

    def _notify_intervention_queued(self, kind: str, target: str | None) -> None:
        """Confirm enqueue to the user. The hook (intervention_pump.py)
        delivers on the next UserPromptSubmit — the cockpit can only
        confirm enqueue, never delivery, so the toast wording stays honest.
        """
        if target:
            display = self._short_node_label(target)
            msg = t(self.lang, "intervention_queued", kind=kind, target=display)
        else:
            msg = t(self.lang, "intervention_queued_no_target", kind=kind)
        # Append the undo hint when an undo pointer is live.
        if self._last_intervention_id is not None:
            msg = msg + " · " + t(self.lang, "intervention_undo_hint")
        self.notify(msg)

    @staticmethod
    def _short_node_label(target: str) -> str:
        """Format ``H_a3f1c2`` → ``H_a3f1`` for compact toast text."""
        if "_" not in target:
            return target[:10]
        prefix, suffix = target.split("_", 1)
        return f"{prefix}_{suffix[:4]}"

    def _require_selected_node(self) -> str | None:
        node_id = self.selected_node_id or self.tree_pane.current_node_id()
        if node_id is None:
            self.notify(t(self.lang, "no_node"), severity="warning")
            return None
        return node_id

    def _refresh_detail(self) -> None:
        if self._detail_override:
            return
        if self.focused_pane == "tabs":
            row = self.tabs_pane.current_row()
            if row is not None:
                title, body = self._row_detail(row)
                self.detail_pane.show_override(title, body)
                return
        self.detail_pane.clear_override()
        self.detail_pane.update_for_node(self.graph, self.selected_node_id)

    def _row_detail(self, row: dict) -> tuple[str, str]:
        return row_detail(row, self.lang)

    def _execute_command(self, command: str) -> None:
        if not command:
            return
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            self.notify(
                t(self.lang, "command_parse_error", error=str(exc)),
                severity="warning",
            )
            return
        if not parts:
            return
        op, *args = parts
        if op == "note":
            data.record_event("note", {"text": " ".join(args)})
        elif op in {"reject", "approve"}:
            target = args[0] if args else self.selected_node_id
            payload = " ".join(args[1:]) if len(args) > 1 else ""
            result = data.write_intervention(op, target, payload)
            self._track_intervention(result, op, target)
        elif op in {"halt", "redirect", "constrain"}:
            if op == "halt":
                result = data.write_intervention(op, None, " ".join(args))
                self._track_intervention(result, op, None)
            else:
                result = data.write_intervention(op, self.selected_node_id, " ".join(args))
                self._track_intervention(result, op, self.selected_node_id)
        elif op == "pin" and len(args) >= 3:
            data.pin_metric_local(
                claim=args[1],
                value=args[2],
                session_id=args[0],
                source_command="cockpit",
                note="pinned from command mode",
            )
        elif op == "goto" and args:
            self._goto_node(args[0])
            return  # _goto_node handles its own refresh; skip the global one
        elif op == "pin":
            self.notify(t(self.lang, "command_pin_usage"), severity="warning")
            return
        else:
            self.notify(
                t(self.lang, "command_unknown", command=op),
                severity="warning",
            )
            return
        self.refresh_state(include_events=True)

    def _goto_node(self, target: str) -> None:
        """Jump tree focus to a node by id or unique prefix.

        Strategy:
          1. Exact match wins immediately.
          2. Otherwise treat ``target`` as a prefix; if exactly one node id
             starts with it, jump. Multiple matches → warning toast listing
             the first few candidates.
          3. Zero matches → warning toast.

        The match runs against the in-memory ``self.graph`` so we never
        block the UI on a SQL round-trip — the snapshot is refreshed on
        each tick anyway.
        """
        if not target:
            return
        nodes = self.graph.nodes
        if target in nodes:
            match = target
        else:
            candidates = [nid for nid in nodes if nid.startswith(target)]
            if len(candidates) == 1:
                match = candidates[0]
            elif len(candidates) > 1:
                preview = ", ".join(candidates[:3])
                more = "" if len(candidates) <= 3 else f" (+{len(candidates) - 3})"
                self.notify(
                    t(
                        self.lang,
                        "goto_ambiguous",
                        target=target,
                        preview=preview + more,
                    ),
                    severity="warning",
                )
                return
            else:
                self.notify(
                    t(self.lang, "goto_not_found", target=target),
                    severity="warning",
                )
                return
        self._set_focus("tree")
        self.tree_pane.select_node_id(match)
        self.selected_node_id = match
        self._refresh_detail()

    def _handle_text_action(self, kind: str, node_id: str, payload: str | None) -> None:
        if payload:
            result = data.write_intervention(kind, node_id, payload)
            self._track_intervention(result, kind, node_id)
            self.refresh_state(include_events=True)

    def _handle_mark_refuted(self, node_id: str, confirmed: bool) -> None:
        if confirmed:
            data.refute_node(node_id, "cockpit refuted")
            # mark_refuted mutates the graph directly (not via the
            # interventions table) so undo doesn't apply — pass None.
            self._track_intervention(None, "refute", node_id)
            self.refresh_state(include_events=True)

    def _handle_pin_metric(self, payload: dict[str, str] | None) -> None:
        if not payload:
            return
        data.pin_metric_local(
            claim=payload["metric"],
            value=payload["value"],
            session_id=payload["dataset"],
            source_command="cockpit",
            note="pinned from cockpit",
        )
        # Pinning writes to ver_metric_pins, not cockpit_interventions —
        # not undoable from the cockpit.
        self._track_intervention(None, "pin", payload["metric"])
        self.refresh_state(include_events=True)

    def _handle_halt(self, confirmed: bool) -> None:
        if confirmed:
            result = data.write_intervention("halt", None, "halt requested from cockpit")
            self._track_intervention(result, "halt", None)
            self.refresh_state(include_events=True)

    def _refresh_graph(self) -> None:
        previous_node_id = self.selected_node_id or self.tree_pane.current_node_id()
        self.graph = data.fetch_graph()
        self.selected_node_id = self.tree_pane.load_graph(
            self.graph,
            show_refuted=self.show_refuted,
            filter_text=self._pane_filters["tree"],
            selected_node_id=previous_node_id,
        )

    def _refresh_tabs(self) -> None:
        failures = data.fetch_failures()
        claims = data.fetch_claims()
        graph = data.fetch_graph()
        heldout_budgets = data.fetch_heldout_budgets()
        self._set_tab_rows(
            risks=data.fetch_risks(
                claims=claims,
                failures=failures,
                graph=graph,
                heldout_budgets=heldout_budgets,
            ),
            failures=failures,
            claims=claims,
            literature=data.fetch_literature(),
            reports=data.fetch_reports(),
            corpus=data.fetch_corpus_problems(),
            diagnostics=data.fetch_diagnostic_manifests(),
            lean=data.fetch_lean_attempts(),
        )

    def _refresh_risks(self) -> None:
        self._set_tab_rows(risks=data.fetch_risks())

    def _refresh_failures(self) -> None:
        failures = data.fetch_failures()
        self._set_tab_rows(failures=failures, risks=data.fetch_risks(failures=failures))

    def _refresh_claims(self) -> None:
        claims = data.fetch_claims()
        self._set_tab_rows(claims=claims, risks=data.fetch_risks(claims=claims))

    def _refresh_literature(self) -> None:
        self._set_tab_rows(literature=data.fetch_literature())

    def _refresh_corpus(self) -> None:
        self._set_tab_rows(corpus=data.fetch_corpus_problems())

    def _refresh_diagnostics(self) -> None:
        self._set_tab_rows(diagnostics=data.fetch_diagnostic_manifests())

    def _refresh_lean(self) -> None:
        self._set_tab_rows(lean=data.fetch_lean_attempts())

    def _refresh_reports(self) -> None:
        self._set_tab_rows(reports=data.fetch_reports())

    def _set_tab_rows(
        self,
        *,
        risks: list[dict] | None = None,
        failures: list[dict] | None = None,
        claims: list[dict] | None = None,
        literature: list[dict] | None = None,
        corpus: list[dict] | None = None,
        diagnostics: list[dict] | None = None,
        lean: list[dict] | None = None,
        reports: list[dict] | None = None,
    ) -> None:
        self.tabs_pane.set_filter_text(self._pane_filters["tabs"])
        self.tabs_pane.set_rows(
            risks=risks if risks is not None else self.tabs_pane.risks_rows,
            failures=failures if failures is not None else self.tabs_pane.failures_rows,
            claims=claims if claims is not None else self.tabs_pane.claims_rows,
            literature=literature if literature is not None else self.tabs_pane.literature_rows,
            corpus=corpus if corpus is not None else self.tabs_pane.corpus_rows,
            diagnostics=(
                diagnostics if diagnostics is not None else self.tabs_pane.diagnostics_rows
            ),
            lean=lean if lean is not None else self.tabs_pane.lean_rows,
            reports=reports if reports is not None else self.tabs_pane.reports_rows,
        )

    def _refresh_counts(self) -> None:
        summary = data.fetch_dashboard()
        self.status_bar.set_summary(summary)
        # Tree border title shows live counts so users get scale info
        # without scanning the HUD. Filter mode takes precedence inside
        # tree_pane.set_counts (see its docstring).
        self.tree_pane.set_counts(
            {
                "active": int(summary.get("active_hypotheses", 0)),
                "refuted": int(summary.get("refuted_nodes", 0)),
            }
        )

    def _refresh_events(self) -> None:
        rows = data.fetch_new_events(self.last_event_id)
        if self.last_event_id <= 0:
            self.events_pane.set_rows(rows)
        elif rows:
            self.events_pane.append_rows(rows)
        self.last_event_id = int(rows[-1]["id"]) if rows else int(data.fetch_latest_event_id())
        self.events_pane.set_filter_text(self._pane_filters["events"])
        self.events_pane.set_relative_timestamps(self.relative_timestamps)

    def _dispatch_events(self, rows: list[dict]) -> None:
        kinds = {str(row.get("kind", "")) for row in rows}
        if {"graph_delta", "judgement_recorded"} & kinds:
            self._refresh_graph()
        if "failure_added" in kinds:
            self._refresh_failures()
        if {"claim_pinned", "seed_run_recorded"} & kinds:
            self._refresh_claims()
        if "literature_ingested" in kinds:
            self._refresh_literature()
        if {"heldout_query_reserved", "heldout_query_finished"} & kinds:
            self._refresh_risks()
        # Proof-trunk per-pane refreshes (v4.1.0a0). Each event class maps
        # to exactly one tab so we don't over-refresh on busy proof loops.
        if "proof_corpus_ingested" in kinds:
            self._refresh_corpus()
        if {
            "proof_segmented",
            "proof_diagnosis_recorded",
            "proof_diagnosis_complete",
            "proof_correction_applied",
        } & kinds:
            self._refresh_diagnostics()
        if {
            "lean_proof_succeeded",
            "lean_proof_failed",
            "lean_proof_recorded",
        } & kinds:
            self._refresh_lean()
        if "report_generated" in kinds:
            self._refresh_reports()
        self._refresh_counts()
        self._refresh_detail()

    def _apply_filter(self, target: str, value: str) -> None:
        self._pane_filters[target] = value
        if target == "tree":
            self.selected_node_id = self.tree_pane.load_graph(
                self.graph,
                show_refuted=self.show_refuted,
                filter_text=value,
                selected_node_id=self.selected_node_id,
            )
        elif target == "events":
            self.events_pane.set_filter_text(value)
        else:
            self.tabs_pane.set_filter_text(value)


def render_snapshot(*, lang: str = "en") -> str:
    """Render a lightweight text snapshot without launching Textual."""

    lang = normalize_lang(lang)
    summary = data.fetch_dashboard()
    graph = data.fetch_graph()
    lines = [
        t(lang, "app_name"),
        _snapshot_summary(lang, summary),
        "",
        t(lang, "tree_title"),
    ]
    visible = graph.visible_ids()
    if not visible:
        lines.append(f"  {t(lang, 'no_hypotheses')}")
    else:
        for node_id in visible[:10]:
            node = graph.node(node_id)
            if node is None:
                continue
            lines.append(f"  {node.node_id} [{node.kind}] {node.text}")
    return "\n".join(lines)


def _snapshot_summary(lang: str, summary: dict) -> str:
    if lang == "zh":
        return (
            f"活跃假设 {summary['active_hypotheses']} / "
            f"已反驳 {summary['refuted_nodes']} / "
            f"指标 {summary['pinned_claims']} / 风险 {summary['risks']}"
        )
    return (
        f"active H {summary['active_hypotheses']} / "
        f"refuted {summary['refuted_nodes']} / "
        f"claims {summary['pinned_claims']} / risks {summary['risks']}"
    )


def main() -> None:
    """Run the cockpit TUI."""
    CockpitApp().run()
