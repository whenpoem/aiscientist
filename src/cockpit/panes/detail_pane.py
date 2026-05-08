"""Detail pane for the cockpit TUI.

Wraps a ``Static`` child in a ``VerticalScroll`` so long content (Lean
stderr, multi-snippet diagnostic manifests, large literature abstracts)
scrolls with the mouse wheel or ``j``/``k`` when the pane is focused.
The public surface (``update``, ``set_language``, ``show_hint`` etc.)
matches the v4.1.0a0 API so callers don't change.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from cockpit.data import GraphNode, GraphSnapshot
from cockpit.details import node_detail_text
from cockpit.i18n import t
from cockpit.theme import style as theme_style


class NodeDetailPane(VerticalScroll):
    """Scrollable detail pane. Renders the selected node or a temporary
    override (failure / claim / corpus / diagnostics / lean drill-in)."""

    def __init__(self) -> None:
        super().__init__()
        self.id = "detail-pane"
        self.classes = "pane"
        self.can_focus = True
        self.lang = "en"
        self.border_title = t(self.lang, "detail_title")
        self._override: str | None = None
        # The body Static carries the actual rendered text. We construct it
        # lazily inside compose() because Textual instantiates widgets
        # before mount and we need access to ``self`` via query_one later.
        self._body = Static("", id="detail-pane-body")

    def compose(self) -> ComposeResult:
        yield self._body

    def on_mount(self) -> None:
        # Initial hint goes through the same path as runtime updates so the
        # i18n + style helpers all work the moment the pane appears.
        self.show_hint()

    # -- public surface (matches v4.1.0a0) --------------------------------

    def update(self, content) -> None:  # type: ignore[override]
        """Forward to the inner Static so callers don't need to know the
        widget is a scroll container with a Static child."""
        self._body.update(content)
        # Reset scroll position when content changes so users always see
        # the start of the new node / drill-in.
        self.scroll_home(animate=False)

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.border_title = t(self.lang, "detail_title")

    def show_hint(self) -> None:
        self._override = None
        self.update(t(self.lang, "select_hint"))

    def show_override(self, title: str, body: str) -> None:
        self._override = body
        text = Text(title, style=theme_style("primary", bold=True))
        text.append("\n\n")
        text.append(body)
        self.update(text)

    def clear_override(self) -> None:
        self._override = None

    def update_for_node(self, graph: GraphSnapshot, node_id: str | None) -> None:
        """Render the active node into the pane.

        Delegates to ``cockpit.details.node_detail_text`` so the main
        detail pane and the full-screen DetailScreen draw from the same
        builder. The pane composes the title (bold, primary color) on
        top of the body for visual hierarchy — the full-screen view does
        the same in its breadcrumb instead.
        """
        if self._override is not None:
            return
        if node_id is None or graph.node(node_id) is None:
            self.show_hint()
            return
        title, body = node_detail_text(graph, node_id, self.lang)
        text = Text(title, style=theme_style("primary", bold=True))
        text.append("\n")
        text.append(body)
        self.update(text)

    # Kept for backwards compatibility with the v4.1.0a4 visual-polish
    # tests that still call this directly. The underlying logic is now
    # in cockpit.details, but unit tests construct GraphNode in isolation
    # and want a synchronous bool/string for assertions.
    def _bt_line(self, node: GraphNode) -> str | None:
        from cockpit.details import _bt_line as _impl

        return _impl(node)
