"""Confirmation modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label

from cockpit.i18n import t


class ConfirmModal(ModalScreen[bool]):
    """Simple y/n confirmation screen."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal #confirm-dialog {
        width: 60;
        height: auto;
        border: round #58a6ff;
        background: #0d1117;
        padding: 1 2;
    }
    ConfirmModal Label {
        width: 1fr;
    }
    """

    def __init__(self, title: str, prompt: str, *, lang: str = "en") -> None:
        super().__init__()
        self._title = title
        self._prompt = prompt
        self._lang = lang

    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            with Vertical():
                yield Label(self._title, id="confirm-title")
                yield Label(self._prompt)
                yield Label(t(self._lang, "confirm_hint"), id="confirm-hint")

    def on_key(self, event) -> None:
        if event.key == "y":
            self.dismiss(True)
            event.stop()
        elif event.key in {"n", "escape"}:
            self.dismiss(False)
            event.stop()
