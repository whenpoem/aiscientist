"""Help modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from cockpit.i18n import t


class HelpScreen(ModalScreen[None]):
    """Read-only overlay showing the important keybindings."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen #help-dialog {
        width: 90;
        height: auto;
        max-height: 85%;
        border: round #58a6ff;
        background: #0d1117;
        padding: 1 2;
    }
    """

    def __init__(self, sections: list[tuple[str, list[tuple[str, str]]]], lang: str) -> None:
        super().__init__()
        self._sections = sections
        self._lang = lang

    def compose(self) -> ComposeResult:
        lines = [t(self._lang, "help_title"), ""]
        for title, bindings in self._sections:
            lines.append(title)
            for key, description in bindings:
                lines.append(f"  {key:<12} {description}")
            lines.append("")
        lines.append(t(self._lang, "help_close"))
        with Container(id="help-dialog"):
            yield Static("\n".join(lines))

    def on_key(self, _event) -> None:
        self.dismiss(None)
