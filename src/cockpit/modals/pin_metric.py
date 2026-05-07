"""Pin metric modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from cockpit.i18n import t


class PinMetricModal(ModalScreen[dict[str, str] | None]):
    """Prompt for dataset, metric, and numeric value."""

    DEFAULT_CSS = """
    PinMetricModal {
        align: center middle;
    }
    PinMetricModal #pin-dialog {
        width: 72;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    PinMetricModal Input {
        margin-top: 1;
        background: $panel;
        color: $foreground;
    }
    PinMetricModal #pin-help {
        color: $foreground-muted;
        margin-top: 1;
    }
    """

    def __init__(self, dataset: str = "", *, lang: str = "en") -> None:
        super().__init__()
        self._default_dataset = dataset
        self._lang = lang

    def compose(self) -> ComposeResult:
        with Container(id="pin-dialog"):
            with Vertical():
                yield Label(t(self._lang, "pin_title"))
                yield Input(
                    value=self._default_dataset,
                    placeholder=t(self._lang, "pin_dataset"),
                    id="pin-dataset",
                )
                yield Input(placeholder=t(self._lang, "pin_metric_field"), id="pin-metric")
                yield Input(placeholder=t(self._lang, "pin_value"), id="pin-value")
                yield Label(t(self._lang, "pin_help"), id="pin-help")

    def on_mount(self) -> None:
        self.query_one("#pin-dataset", Input).focus()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
            return
        if event.key == "tab":
            self.focus_next()
            event.stop()
            return
        if event.key == "shift+tab":
            self.focus_previous()
            event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "pin-value":
            self.focus_next()
            return
        dataset = self.query_one("#pin-dataset", Input).value.strip()
        metric = self.query_one("#pin-metric", Input).value.strip()
        value = self.query_one("#pin-value", Input).value.strip()
        if not dataset or not metric or not value:
            return
        try:
            float(value)
        except ValueError:
            return
        self.dismiss({"dataset": dataset, "metric": metric, "value": value})
