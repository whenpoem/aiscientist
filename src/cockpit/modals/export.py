"""Export modal — pick a report kind and format(s) for the active node.

The ``e`` key on a focused node (tree pane) opens this modal. The
list of kinds is filtered by node kind via
``cockpit.export.pipeline.kinds_for_node_kind``; format defaults to
markdown but can be flipped to ``html`` or ``both`` via a single
keystroke (``m`` / ``h`` / ``b``).

Submission returns an ``ExportRequest`` dataclass; cancel returns
``None``.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label

from cockpit.i18n import t


@dataclass(frozen=True)
class ExportRequest:
    """User's pick from the ExportModal. ``formats`` always non-empty."""

    kind: str
    formats: tuple[str, ...]


class ExportModal(ModalScreen[ExportRequest | None]):
    """Choose a report kind + format(s) for the export pipeline."""

    DEFAULT_CSS = """
    ExportModal {
        align: center middle;
    }
    ExportModal #export-dialog {
        width: 64;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    ExportModal Label {
        width: 1fr;
    }
    ExportModal #export-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    ExportModal .kind-line {
        padding: 0 1;
    }
    ExportModal .kind-line-active {
        padding: 0 1;
        background: $boost;
        color: $foreground;
    }
    ExportModal #export-format-line {
        margin-top: 1;
        color: $foreground-muted;
    }
    ExportModal #export-hint {
        margin-top: 1;
        color: $foreground 70%;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", show=False, priority=True),
        Binding("enter", "submit", show=False, priority=True),
        Binding("up", "prev_kind", show=False, priority=True),
        Binding("down", "next_kind", show=False, priority=True),
        Binding("j", "next_kind", show=False, priority=True),
        Binding("k", "prev_kind", show=False, priority=True),
        Binding("m", "set_format_md", show=False, priority=True),
        Binding("h", "set_format_html", show=False, priority=True),
        Binding("b", "set_format_both", show=False, priority=True),
    ]

    def __init__(
        self,
        node_id: str,
        kinds: tuple[str, ...],
        *,
        lang: str = "en",
    ) -> None:
        super().__init__()
        self._node_id = node_id
        self._kinds = tuple(kinds)
        self._lang = lang
        self._kind_idx = 0
        self._format = "md"  # md | html | both

    def compose(self) -> ComposeResult:
        with Container(id="export-dialog"):
            with Vertical():
                yield Label(
                    t(self._lang, "export_modal_title") + f"  ({self._node_id})",
                    id="export-title",
                )
                if not self._kinds:
                    yield Label(
                        t(self._lang, "export_no_kinds_available"),
                        id="export-empty",
                    )
                else:
                    for idx, kind in enumerate(self._kinds):
                        label = t(self._lang, f"export_kind_{kind}")
                        if label == f"export_kind_{kind}":
                            label = kind
                        css_class = "kind-line-active" if idx == 0 else "kind-line"
                        yield Label(
                            f"  {label}",
                            id=f"export-kind-{idx}",
                            classes=css_class,
                        )
                yield Label("", id="export-format-line")
                yield Label(
                    "  ↑/↓ pick · m markdown · h html · b both · "
                    "Enter export · Esc cancel",
                    id="export-hint",
                )

    def on_mount(self) -> None:
        self._refresh_format_line()

    # ----- key handlers --------------------------------------------------

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        if not self._kinds:
            self.dismiss(None)
            return
        chosen_kind = self._kinds[self._kind_idx]
        if self._format == "both":
            formats: tuple[str, ...] = ("md", "html")
        else:
            formats = (self._format,)
        self.dismiss(ExportRequest(kind=chosen_kind, formats=formats))

    def action_next_kind(self) -> None:
        if not self._kinds:
            return
        self._set_kind_idx((self._kind_idx + 1) % len(self._kinds))

    def action_prev_kind(self) -> None:
        if not self._kinds:
            return
        self._set_kind_idx((self._kind_idx - 1) % len(self._kinds))

    def action_set_format_md(self) -> None:
        self._format = "md"
        self._refresh_format_line()

    def action_set_format_html(self) -> None:
        self._format = "html"
        self._refresh_format_line()

    def action_set_format_both(self) -> None:
        self._format = "both"
        self._refresh_format_line()

    # ----- internals -----------------------------------------------------

    def _set_kind_idx(self, new_idx: int) -> None:
        prev_idx = self._kind_idx
        self._kind_idx = new_idx
        for idx in (prev_idx, new_idx):
            try:
                label = self.query_one(f"#export-kind-{idx}", Label)
            except Exception:  # pragma: no cover - defensive
                continue
            if idx == new_idx:
                label.set_classes("kind-line-active")
            else:
                label.set_classes("kind-line")

    def _refresh_format_line(self) -> None:
        if self._format == "md":
            text = t(self._lang, "export_format_md")
        elif self._format == "html":
            text = t(self._lang, "export_format_html")
        else:
            text = t(self._lang, "export_format_both")
        try:
            self.query_one("#export-format-line", Label).update(
                f"  format: {text}"
            )
        except Exception:  # pragma: no cover - defensive
            pass
