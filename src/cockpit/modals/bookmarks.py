"""Bookmarks navigator modal.

Phase E3: when the user presses ``B`` (capital) in the cockpit, this
modal opens showing every node that has been bookmarked via ``b``
(lowercase) in the tree pane. ``j`` / ``k`` walks the list, Enter
jumps the tree selection to that node and dismisses the modal,
``d`` deletes the highlighted bookmark, Esc / ``q`` closes without
jumping.

The pane is intentionally read-only beyond delete: bookmark *creation*
happens via the tree-pane ``b`` keystroke so the user is always pinning
the node they just looked at. Creating from the modal would mean
typing a node id with no completion, which is the kind of friction
that kills the feature.

The dismiss result is one of:

- ``None`` — user cancelled (Esc / ``q`` / no bookmarks defined)
- ``("jump", node_id)`` — user pressed Enter on a bookmarked row
- ``("delete", node_id)`` — user pressed ``d`` to remove a row

The App handles each tuple kind in its callback. Splitting these
shapes (rather than a single ``str`` result) keeps the modal honest
about the "delete" action — without the tuple the App would have to
re-implement the deletion logic.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from cockpit.data import GraphSnapshot
from cockpit.i18n import t


class BookmarksModal(ModalScreen):
    """List + navigate the user's bookmarked node ids."""

    DEFAULT_CSS = """
    BookmarksModal {
        align: center middle;
    }
    BookmarksModal #bookmarks-dialog {
        width: 70;
        height: auto;
        max-height: 70%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    BookmarksModal #bookmarks-title {
        color: $primary;
        text-style: bold;
    }
    BookmarksModal #bookmarks-hint {
        color: $foreground-muted;
        margin-top: 1;
    }
    BookmarksModal ListView {
        height: auto;
        max-height: 20;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("q", "close", show=False),
        Binding("enter", "jump", show=False, priority=True),
        Binding("d", "delete", show=False, priority=True),
        Binding("j", "down", show=False),
        Binding("k", "up", show=False),
    ]

    def __init__(
        self,
        bookmarks: list[str],
        graph: GraphSnapshot | None,
        *,
        lang: str = "en",
    ) -> None:
        super().__init__()
        self._bookmarks = list(bookmarks)
        self._graph = graph
        self._lang = lang

    def compose(self) -> ComposeResult:
        with Container(id="bookmarks-dialog"):
            with Vertical():
                yield Label(t(self._lang, "bookmarks_title"), id="bookmarks-title")
                if not self._bookmarks:
                    yield Label(
                        t(self._lang, "bookmarks_empty"),
                        id="bookmarks-empty",
                    )
                else:
                    yield ListView(
                        *[
                            ListItem(Label(self._render_row(node_id)))
                            for node_id in self._bookmarks
                        ],
                        id="bookmarks-list",
                    )
                yield Label(
                    t(self._lang, "bookmarks_hint"),
                    id="bookmarks-hint",
                )

    def _render_row(self, node_id: str) -> str:
        """Render one row as ``<node_id> · <short text>``.

        The short text comes from the graph snapshot when available so
        the user sees what the bookmark *means*, not just a cryptic id.
        Bookmarks pointing at deleted nodes still render — they show
        the id alone (the user can decide to delete the dead row).
        """
        if self._graph is not None:
            node = self._graph.node(node_id)
            if node is not None and node.text:
                preview = node.text[:60]
                if len(node.text) > 60:
                    preview += "…"
                return f"{node_id}  ·  {preview}"
        return node_id

    def _current_node_id(self) -> str | None:
        if not self._bookmarks:
            return None
        try:
            listview = self.query_one("#bookmarks-list", ListView)
        except Exception:  # pragma: no cover - defensive
            return None
        idx = listview.index
        if idx is None or idx < 0 or idx >= len(self._bookmarks):
            return None
        return self._bookmarks[idx]

    def action_close(self) -> None:
        self.dismiss(None)

    def action_jump(self) -> None:
        node_id = self._current_node_id()
        if node_id is None:
            self.dismiss(None)
            return
        self.dismiss(("jump", node_id))

    def on_list_view_selected(self, _event: ListView.Selected) -> None:
        """Treat ListView's submit event as Enter-to-jump.

        The app owns a priority Enter binding so it can forward Enter
        into modals and command inputs. For a focused ListView that
        forwarding path calls ``ListView.action_submit()``, which emits
        ``ListView.Selected`` rather than invoking this modal's own
        ``action_jump`` binding. Handling the message here keeps both
        paths equivalent: direct modal binding and app-forwarded Enter.
        """
        self.action_jump()

    def action_delete(self) -> None:
        node_id = self._current_node_id()
        if node_id is None:
            self.dismiss(None)
            return
        self.dismiss(("delete", node_id))

    def action_down(self) -> None:
        try:
            self.query_one("#bookmarks-list", ListView).action_cursor_down()
        except Exception:  # pragma: no cover - defensive
            pass

    def action_up(self) -> None:
        try:
            self.query_one("#bookmarks-list", ListView).action_cursor_up()
        except Exception:  # pragma: no cover - defensive
            pass
