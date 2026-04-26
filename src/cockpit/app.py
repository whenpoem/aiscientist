"""Textual cockpit application."""

from __future__ import annotations

import asyncio
import shlex
from datetime import datetime, timezone
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Footer, Input, Static

from . import data
from .i18n import normalize_lang, t, toggle_lang
from .modals import ConfirmModal, HelpScreen, PinMetricModal, TextInputModal
from .panes import EventStreamPane, HypothesisTreePane, NodeDetailPane, RightTabsPane

FOCUS_ORDER = ("tree", "detail", "events", "tabs")


class StatusBar(Static):
    """Single-line status header."""

    def __init__(self, *, lang: str = "en") -> None:
        super().__init__("")
        self.id = "status-bar"
        self.lang = normalize_lang(lang)
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

    def set_summary(self, summary: dict) -> None:
        self._summary = dict(summary)
        self._refresh_display()

    def _tick(self) -> None:
        self._clock = datetime.now().strftime("%H:%M")
        self._refresh_display()

    def _refresh_display(self) -> None:
        self.current_text = t(
            self.lang,
            "hud",
            app=t(self.lang, "app_name"),
            active_hypotheses=self._summary.get("active_hypotheses", 0),
            refuted_nodes=self._summary.get("refuted_nodes", 0),
            pinned_claims=self._summary.get("pinned_claims", 0),
            unverified_claims=self._summary.get("unverified_claims", 0),
            heldout=self._format_heldout(),
            risks=self._summary.get("risks", 0),
            last_event=self._format_last_event(),
            clock=self._clock,
        )
        self.update(self.current_text)

    def _format_heldout(self) -> str:
        budgets = self._summary.get("heldout_budgets") or []
        if not budgets:
            return t(self.lang, "heldout_none")
        parts = [
            f"{row.get('dataset', '-')}: {row.get('budget_used', 0)}/{row.get('budget_total', 0)}"
            for row in budgets[:2]
        ]
        return ", ".join(parts)

    def _format_last_event(self) -> str:
        raw = self._summary.get("latest_event_at")
        if not raw:
            return t(self.lang, "last_never")
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return str(raw)[:8]
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        seconds = max(int(delta.total_seconds()), 0)
        if seconds < 5:
            return t(self.lang, "just_now")
        if seconds < 60:
            return t(self.lang, "seconds_ago", value=seconds)
        minutes = seconds // 60
        if minutes < 60:
            return t(self.lang, "minutes_ago", value=minutes)
        return t(self.lang, "hours_ago", value=minutes // 60)


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
    BINDINGS = [
        Binding("1", "focus_tree", "Tree"),
        Binding("2", "focus_detail", "Detail"),
        Binding("3", "focus_events", "Events"),
        Binding("4", "focus_tabs", "Tabs"),
        Binding("tab", "focus_next_pane", "Next Pane"),
        Binding("shift+tab", "focus_prev_pane", "Prev Pane"),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
        Binding("h", "pane_left", "Left"),
        Binding("l", "pane_right", "Right"),
        Binding("g", "jump_top", "Top"),
        Binding("G", "jump_bottom", "Bottom"),
        Binding("f", "cycle_right_tab", "Cycle Tab"),
        Binding("enter", "drill_selection", "Open"),
        Binding("y", "approve_node", "Approve"),
        Binding("n", "reject_node", "Reject"),
        Binding("r", "redirect_node", "Redirect"),
        Binding("c", "constrain_node", "Constrain"),
        Binding("m", "mark_refuted", "Refute"),
        Binding("p", "pin_metric", "Pin"),
        Binding("H", "halt_agent", "Halt"),
        Binding("/", "open_filter", "Filter"),
        Binding(":", "open_command", "Command"),
        Binding("?", "show_help", "Help"),
        Binding("t", "toggle_timestamp_mode", "Time"),
        Binding("s", "toggle_refuted", "Refuted"),
        Binding("L", "toggle_language", "Language"),
        Binding("R", "force_refresh", "Refresh"),
        Binding("ctrl+l", "clear_event_log", "Clear Events"),
        Binding("escape", "cancel_context", show=False),
        Binding("q", "quit_requested", "Quit"),
    ]

    focused_pane = reactive("tree")
    show_refuted = reactive(False)
    relative_timestamps = reactive(False)
    last_event_id = reactive(0)

    def __init__(self, *, lang: str = "en") -> None:
        super().__init__()
        self.lang = normalize_lang(lang)
        self.graph = data.GraphSnapshot(nodes={})
        self.selected_node_id: str | None = None
        self._command_mode: str | None = None
        self._command_target = "tree"
        self._pane_filters = {"tree": "", "events": "", "tabs": ""}
        self._detail_override = False
        self._stop_event_worker = False

    def compose(self) -> ComposeResult:
        yield StatusBar(lang=self.lang)
        with Container(id="body-grid"):
            yield HypothesisTreePane()
            yield NodeDetailPane()
            yield EventStreamPane()
            yield RightTabsPane()
        yield Input(placeholder="command", id="command-line", classes="hidden")
        yield ContextBar(lang=self.lang)
        yield Footer()

    def on_mount(self) -> None:
        self._apply_language()
        self.refresh_state(include_events=True)
        self._set_focus("tree")
        self.events_worker()

    def on_unmount(self) -> None:
        self._stop_event_worker = True

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
        index = FOCUS_ORDER.index(self.focused_pane)
        self._set_focus(FOCUS_ORDER[(index + 1) % len(FOCUS_ORDER)])

    def action_focus_prev_pane(self) -> None:
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

    def action_show_help(self) -> None:
        sections = [
            (
                t(self.lang, "help_navigation"),
                [
                    ("j / k", t(self.lang, "move_selection")),
                    ("h / l", t(self.lang, "collapse_expand")),
                    ("1-4", t(self.lang, "jump_pane")),
                    ("Tab", t(self.lang, "cycle_panes")),
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
        self.lang = toggle_lang(self.lang)
        self._apply_language()
        self.refresh_state(include_events=True)
        self.notify(t(self.lang, "language_notice"))

    def action_toggle_timestamp_mode(self) -> None:
        self.relative_timestamps = not self.relative_timestamps
        self.events_pane.set_relative_timestamps(self.relative_timestamps)

    def action_toggle_refuted(self) -> None:
        self.show_refuted = not self.show_refuted
        self.selected_node_id = self.tree_pane.load_graph(
            self.graph,
            show_refuted=self.show_refuted,
            filter_text=self._pane_filters["tree"],
            selected_node_id=self.selected_node_id,
        )
        self._refresh_detail()

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

    def action_drill_selection(self) -> None:
        if self.focused_pane != "tabs":
            return
        row = self.tabs_pane.current_row()
        if row is None:
            return
        title, body = self._row_detail(row)
        self._detail_override = True
        self.detail_pane.show_override(title, body)

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
        target = {
            "tree": self.tree_pane,
            "detail": self.detail_pane,
            "events": self.events_pane,
            "tabs": self.tabs_pane.current_table(),
        }[pane_name]
        target.focus()

    def _apply_language(self) -> None:
        self.status_bar.set_language(self.lang)
        self.context_bar.set_language(self.lang)
        self.tree_pane.set_language(self.lang)
        self.detail_pane.set_language(self.lang)
        self.events_pane.set_language(self.lang)
        self.tabs_pane.set_language(self.lang)
        self.context_bar.set_pane(self.focused_pane)

    def _show_command_line(self, mode: str, placeholder: str, *, target: str = "tree") -> None:
        self._command_mode = mode
        self._command_target = target
        self.command_line.placeholder = placeholder
        self.command_line.value = self._pane_filters.get(target, "") if mode == "filter" else ""
        self.command_line.remove_class("hidden")
        self.command_line.focus()
        self.command_line.action_end()

    def _hide_command_line(self, *, clear_filter: bool = False) -> None:
        mode = self._command_mode
        target = self._command_target
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
        data.write_intervention(kind, node_id, "")
        self.refresh_state(include_events=True)

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
        if {"severity", "category", "summary"} <= set(row):
            return (
                f"{t(self.lang, 'risks')} {row['item']}",
                "\n".join(
                    [
                        f"{t(self.lang, 'severity')}: {row['severity']}",
                        f"{t(self.lang, 'category')}: {row['category']}",
                        f"{t(self.lang, 'summary')}: {row['summary']}",
                    ]
                ),
            )
        if "failure_id" in row:
            return (
                f"{t(self.lang, 'failures')} #{row['failure_id']}",
                "\n".join(
                    [
                        f"{t(self.lang, 'trigger')}: {row['trigger']}",
                        f"{t(self.lang, 'symptom')}: {row['symptom']}",
                        f"Root cause: {row.get('root_cause') or '-'}",
                        f"Resolution: {row.get('resolution') or '-'}",
                        f"{t(self.lang, 'seen')}: {row.get('seen_count', 0)}",
                        f"Signature: {row.get('signature') or '-'}",
                    ]
                ),
            )
        if "pin_id" in row:
            return (
                f"{t(self.lang, 'claims')} {row['metric']}",
                "\n".join(
                    [
                        f"{t(self.lang, 'value')}: {row['value']}",
                        f"{t(self.lang, 'dataset')}: {row['dataset']}",
                        f"{t(self.lang, 'verified')}: "
                        f"{t(self.lang, 'yes') if row['verified'] else t(self.lang, 'no')}",
                        f"{t(self.lang, 'seeds')}: {row['seeds']}",
                        f"Note: {row.get('note') or '-'}",
                        f"Source: {row.get('source_command') or '-'}",
                    ]
                ),
            )
        return (
            f"{t(self.lang, 'literature')} {row['paper_id']}",
            "\n".join(
                [
                    row.get("title", ""),
                    f"{t(self.lang, 'year')}: {row.get('year') or '-'}",
                    f"{t(self.lang, 'task')}: {row.get('task') or '-'}",
                    f"{t(self.lang, 'score')}: {float(row.get('score') or 0.0):.2f}",
                    f"Venue: {row.get('venue') or '-'}",
                    f"Source: {row.get('source') or '-'}",
                ]
            ),
        )

    def _execute_command(self, command: str) -> None:
        if not command:
            return
        parts = shlex.split(command)
        if not parts:
            return
        op, *args = parts
        if op == "note":
            data.record_event("note", {"text": " ".join(args)})
        elif op in {"reject", "approve"}:
            target = args[0] if args else self.selected_node_id
            payload = " ".join(args[1:]) if len(args) > 1 else ""
            data.write_intervention(op, target, payload)
        elif op in {"halt", "redirect", "constrain"}:
            if op == "halt":
                data.write_intervention(op, None, " ".join(args))
            else:
                data.write_intervention(op, self.selected_node_id, " ".join(args))
        elif op == "pin" and len(args) >= 3:
            data.pin_metric_local(
                claim=args[1],
                value=args[2],
                session_id=args[0],
                source_command="cockpit",
                note="pinned from command mode",
            )
        self.refresh_state(include_events=True)

    def _handle_text_action(self, kind: str, node_id: str, payload: str | None) -> None:
        if payload:
            data.write_intervention(kind, node_id, payload)
            self.refresh_state(include_events=True)

    def _handle_mark_refuted(self, node_id: str, confirmed: bool) -> None:
        if confirmed:
            data.refute_node(node_id, "cockpit refuted")
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
        self.refresh_state(include_events=True)

    def _handle_halt(self, confirmed: bool) -> None:
        if confirmed:
            data.write_intervention("halt", None, "halt requested from cockpit")
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

    def _set_tab_rows(
        self,
        *,
        risks: list[dict] | None = None,
        failures: list[dict] | None = None,
        claims: list[dict] | None = None,
        literature: list[dict] | None = None,
    ) -> None:
        self.tabs_pane.set_filter_text(self._pane_filters["tabs"])
        self.tabs_pane.set_rows(
            risks=risks if risks is not None else self.tabs_pane.risks_rows,
            failures=failures if failures is not None else self.tabs_pane.failures_rows,
            claims=claims if claims is not None else self.tabs_pane.claims_rows,
            literature=literature if literature is not None else self.tabs_pane.literature_rows,
        )

    def _refresh_counts(self) -> None:
        self.status_bar.set_summary(data.fetch_dashboard())

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
