"""Single-line text input modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class TextInputModal(ModalScreen[str | None]):
    """Prompt for a short line of text."""

    DEFAULT_CSS = """
    TextInputModal {
        align: center middle;
    }
    TextInputModal #text-input-dialog {
        width: 72;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    TextInputModal Input {
        background: $panel;
        color: $foreground;
    }
    """

    def __init__(self, title: str, placeholder: str) -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Container(id="text-input-dialog"):
            with Vertical():
                yield Label(self._title)
                yield Input(placeholder=self._placeholder, id="text-input-field")

    def on_mount(self) -> None:
        self.query_one("#text-input-field", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
