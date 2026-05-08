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
        border: round $primary;
        background: $surface;
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

    # Keys that close the help overlay. Anything else is consumed silently
    # so the user reading the keymap can't accidentally fire a destructive
    # action (e.g. `y` approving the selected node) just by tapping a key.
    # `?` is symmetric to the trigger; `enter`/`space` cover muscle memory.
    _DISMISS_KEYS = frozenset({"escape", "enter", "space", "question_mark", "?"})

    def on_key(self, event) -> None:
        if event.key in self._DISMISS_KEYS:
            self.dismiss(None)
        # Stop propagation either way: if the user pressed a stray key we
        # don't want it bubbling to the underlying app and triggering an
        # action while the help overlay is visible.
        event.stop()
