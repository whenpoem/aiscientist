"""Textual cockpit application."""

from __future__ import annotations

import asyncio
import shlex
from datetime import datetime
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Footer, Input, Static

from memory_mcp import impl as memory_impl
from verify_mcp import impl as verify_impl

from . import data
from .modals import ConfirmModal, HelpScreen, PinMetricModal, TextInputModal
from .panes import EventStreamPane, HypothesisTreePane, NodeDetailPane, RightTabsPane

FOCUS_ORDER = ("tree", "detail", "events", "tabs")


class StatusBar(Static):
    """Single-line status header."""

    def __init__(self) -> None:
        super().__init__("")
        self.id = "status-bar"
        self._counts = {"nodes": 0, "failures": 0, "events": 0, "interventions": 0}
        self._clock = "--:--"

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)
        self._refresh_display()

    def set_counts(self, counts: dict[str, int]) -> None:
        self._counts = dict(counts)
        self._refresh_display()

    def _tick(self) -> None:
        self._clock = datetime.now().strftime("%H:%M")
        self._refresh_display()

    def _refresh_display(self) -> None:
        self.update(
            "research-cockpit  "
            f"state.db: {self._counts['nodes']} nodes / {self._counts['failures']} failures / "
            f"{self._counts['events']} events  {self._clock}"
        )


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
        Binding("R", "force_refresh", "Refresh"),
        Binding("ctrl+l", "clear_event_log", "Clear Events"),
        Binding("escape", "cancel_context", show=False),
        Binding("q", "quit_requested", "Quit"),
    ]

    focused_pane = reactive("tree")
    show_refuted = reactive(False)
    relative_timestamps = reactive(False)
    last_event_id = reactive(0)

    def __init__(self) -> None:
        super().__init__()
        self.graph = data.GraphSnapshot(nodes={})
        self.selected_node_id: str | None = None
        self._command_mode: str | None = None
        self._command_target = "tree"
        self._pane_filters = {"tree": "", "events": "", "tabs": ""}
        self._detail_override = False
        self._stop_event_worker = False

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with Container(id="body-grid"):
            yield HypothesisTreePane()
            yield NodeDetailPane()
            yield EventStreamPane()
            yield RightTabsPane()
        yield Input(placeholder="command", id="command-line", classes="hidden")
        yield Footer()

    def on_mount(self) -> None:
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

    def refresh_state(self, *, include_events: bool) -> None:
        previous_node_id = self.selected_node_id or self.tree_pane.current_node_id()
        self.graph = data.fetch_graph()
        self.selected_node_id = self.tree_pane.load_graph(
            self.graph,
            show_refuted=self.show_refuted,
            filter_text=self._pane_filters["tree"],
            selected_node_id=previous_node_id,
        )
        self.tabs_pane.set_filter_text(self._pane_filters["tabs"])
        self.tabs_pane.set_rows(
            failures=data.fetch_failures(),
            claims=data.fetch_claims(),
            literature=data.fetch_literature(),
        )
        self.status_bar.set_counts(data.fetch_counts())
        if include_events:
            rows = data.fetch_new_events(self.last_event_id)
            if rows:
                self.events_pane.append_rows(rows)
                self.last_event_id = int(rows[-1]["id"])
            else:
                self.last_event_id = int(data.fetch_latest_event_id())
                self.events_pane.set_rows(data.fetch_new_events(0))
        self.events_pane.set_filter_text(self._pane_filters["events"])
        self.events_pane.set_relative_timestamps(self.relative_timestamps)
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
            self._refresh_detail()

    def on_key(self, event) -> None:
        if event.key == "escape" and not self.command_line.has_class("hidden"):
            self._hide_command_line()
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
                "Navigation",
                [
                    ("j / k", "move selection"),
                    ("h / l", "collapse/expand or move focus"),
                    ("1-4", "jump to pane"),
                    ("Tab", "cycle panes"),
                ],
            ),
            (
                "Actions",
                [
                    ("y / n", "approve or reject"),
                    ("r / c", "redirect or constrain"),
                    ("m", "mark refuted"),
                    ("p", "pin metric"),
                    ("H", "halt agent"),
                ],
            ),
            (
                "Meta",
                [
                    ("/", "filter"),
                    (":", "command mode"),
                    ("t", "toggle timestamps"),
                    ("s", "toggle refuted"),
                    ("q", "quit"),
                ],
            ),
        ]
        self.push_screen(HelpScreen(sections))

    def action_open_command(self) -> None:
        self._show_command_line("command", "Enter command, e.g. note remember baseline")

    def action_open_filter(self) -> None:
        target = self.focused_pane if self.focused_pane in {"tree", "events", "tabs"} else "tree"
        placeholder = {
            "tree": "Filter hypothesis tree",
            "events": "Filter event stream",
            "tabs": "Filter active right tab",
        }[target]
        self._show_command_line("filter", placeholder, target=target)

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
            self._hide_command_line()
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
            TextInputModal("Redirect hypothesis", "Enter redirect text"),
            callback=lambda payload, node_id=node_id: self._handle_text_action(
                "redirect", node_id, payload
            ),
        )

    def action_constrain_node(self) -> None:
        node_id = self._require_selected_node()
        if node_id is None:
            return
        self.push_screen(
            TextInputModal("Constrain hypothesis", "Enter constraint text"),
            callback=lambda payload, node_id=node_id: self._handle_text_action(
                "constrain", node_id, payload
            ),
        )

    def action_mark_refuted(self) -> None:
        node_id = self._require_selected_node()
        if node_id is None:
            return
        self.push_screen(
            ConfirmModal("Mark Refuted", f"Mark {node_id} as refuted?"),
            callback=lambda confirmed, node_id=node_id: self._handle_mark_refuted(
                node_id, confirmed
            ),
        )

    def action_pin_metric(self) -> None:
        dataset = self.selected_node_id or "session"
        self.push_screen(PinMetricModal(dataset=dataset), callback=self._handle_pin_metric)

    def action_halt_agent(self) -> None:
        self.push_screen(
            ConfirmModal("Halt Agent", "Queue a halt intervention?"),
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
                self.refresh_state(include_events=False)
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

    def _show_command_line(self, mode: str, placeholder: str, *, target: str = "tree") -> None:
        self._command_mode = mode
        self._command_target = target
        self.command_line.placeholder = placeholder
        self.command_line.value = self._pane_filters.get(target, "") if mode == "filter" else ""
        self.command_line.remove_class("hidden")
        self.command_line.focus()
        self.command_line.action_end()

    def _hide_command_line(self) -> None:
        self.command_line.value = ""
        self.command_line.add_class("hidden")
        self._command_mode = None
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
            self.notify("No node selected.", severity="warning")
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
        if "failure_id" in row:
            return (
                f"Failure #{row['failure_id']}",
                "\n".join(
                    [
                        f"Trigger: {row['trigger']}",
                        f"Symptom: {row['symptom']}",
                        f"Root cause: {row.get('root_cause') or '-'}",
                        f"Resolution: {row.get('resolution') or '-'}",
                        f"Seen: {row.get('seen_count', 0)}",
                        f"Signature: {row.get('signature') or '-'}",
                    ]
                ),
            )
        if "pin_id" in row:
            return (
                f"Claim {row['metric']}",
                "\n".join(
                    [
                        f"Value: {row['value']}",
                        f"Dataset: {row['dataset']}",
                        f"Verified: {'yes' if row['verified'] else 'no'}",
                        f"Seeds: {row['seeds']}",
                        f"Note: {row.get('note') or '-'}",
                        f"Source: {row.get('source_command') or '-'}",
                    ]
                ),
            )
        return (
            f"Paper {row['paper_id']}",
            "\n".join(
                [
                    row.get("title", ""),
                    f"Year: {row.get('year') or '-'}",
                    f"Task: {row.get('task') or '-'}",
                    f"Score: {float(row.get('score') or 0.0):.2f}",
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
            verify_impl.pin_metric(
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
            memory_impl.mark_refuted(node_id, "cockpit refuted")
            self.refresh_state(include_events=True)

    def _handle_pin_metric(self, payload: dict[str, str] | None) -> None:
        if not payload:
            return
        verify_impl.pin_metric(
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


def render_snapshot() -> str:
    """Render a lightweight text snapshot without launching Textual."""

    counts = data.fetch_counts()
    graph = data.fetch_graph()
    lines = [
        "research-cockpit",
        (
            f"state.db: {counts['nodes']} nodes / {counts['failures']} failures / "
            f"{counts['events']} events"
        ),
        "",
        "Hypothesis Tree",
    ]
    visible = graph.visible_ids()
    if not visible:
        lines.append("  No hypotheses yet.")
    else:
        for node_id in visible[:10]:
            node = graph.node(node_id)
            if node is None:
                continue
            lines.append(f"  {node.node_id} [{node.kind}] {node.text}")
    return "\n".join(lines)


def main() -> None:
    """Run the cockpit TUI."""
    CockpitApp().run()
