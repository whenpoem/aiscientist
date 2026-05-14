"""Detail pane for the cockpit TUI.

Wraps a stack of Textual ``Collapsible`` widgets in a ``VerticalScroll``.
Each Collapsible holds one section of the node detail view (overview,
BT strength, children, cross edges, related failures). Drill-in from
tab rows uses the same pane but bypasses sectioning — drill-in payloads
are single-text snippets, so they render in a Static "banner" view that
takes over the pane while the override is active.

Public surface (``update``, ``set_language``, ``show_hint``,
``show_override``, ``clear_override``, ``update_for_node``) matches the
v4.1 API so the App doesn't need to know about Collapsibles.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Static

from cockpit.data import GraphNode, GraphSnapshot
from cockpit.details import SECTION_KEYS, node_detail_sections
from cockpit.i18n import t
from cockpit.theme import style as theme_style


class NodeDetailPane(VerticalScroll):
    """Scrollable detail pane. Renders the selected node (sectioned) or
    a temporary override (failure / claim / corpus / diagnostics / lean
    drill-in, hint text)."""

    def __init__(self) -> None:
        super().__init__()
        self.id = "detail-pane"
        self.classes = "pane"
        self.can_focus = True
        self.lang = "en"
        self.border_title = t(self.lang, "detail_title")
        # Three rendering modes:
        #   "hint"     — initial / empty-state hint text
        #   "override" — tab drill-in payload (single Text)
        #   "node"     — sectioned graph-node view
        self._mode = "hint"
        self._override_text: Text | None = None
        # Phase C: breadcrumb above the banner. Tells the user where the
        # current content came from (Tree selection vs Tabs drill-in) so
        # the multi-source pane stops feeling magical. In drill-in mode
        # the breadcrumb also hints "Esc to return" so the escape path
        # is discoverable without reading the help screen.
        self._breadcrumb = Static("", id="detail-pane-breadcrumb")
        # Title banner doubles as the override body holder. In "node"
        # mode it carries just the node's short id + kind label; in
        # "override" / "hint" mode it carries the entire payload.
        self._banner = Static("", id="detail-pane-banner")
        # Each section key gets a pre-allocated Collapsible. Empty
        # sections (no children, no cross edges) get their slot's
        # display flipped to none during update_for_node.
        self._section_widgets: dict[str, Collapsible] = {}
        self._section_bodies: dict[str, Static] = {}
        # User-controlled collapsed state (settings-backed). The App
        # injects this via set_section_collapsed_state on mount so the
        # pane and the settings stay in sync without the pane reaching
        # into the App.
        self._collapsed_state: dict[str, bool] = {}
        # Callback fired when the user toggles a section. Wired by the
        # App so the toggle persists to settings.
        self._on_section_toggled = None
        # Latest breadcrumb args, kept so set_language() can re-render
        # the localized text without the App needing to push values
        # through again on every language toggle.
        self._breadcrumb_state: tuple[str, dict] = ("hint", {})

    def compose(self) -> ComposeResult:
        yield self._breadcrumb
        yield self._banner
        for key in SECTION_KEYS:
            body = Static("", id=f"detail-section-{key}-body")
            self._section_bodies[key] = body
            collapsible = Collapsible(
                body,
                title="",
                id=f"detail-section-{key}",
                collapsed=False,
                classes="detail-section",
            )
            self._section_widgets[key] = collapsible
            yield collapsible

    def on_mount(self) -> None:
        self.show_hint()

    # -- App-injected dependencies ----------------------------------------

    def set_section_collapsed_state(self, state: dict[str, bool]) -> None:
        """Inject the persisted per-section collapsed state.

        Called by the App once on mount and again whenever the user
        switches language or theme. The pane consults this dict on
        every ``update_for_node`` to set each Collapsible's initial
        state; user toggles fire ``_on_section_toggled``.
        """
        self._collapsed_state = dict(state)

    def set_section_toggle_callback(self, callback) -> None:
        """Wire a callback fired when the user toggles a section.

        Signature: ``callback(section_key: str, collapsed: bool) -> None``.
        Used by the App to persist the change to ``CockpitSettings``.
        """
        self._on_section_toggled = callback

    # -- public surface (matches v4.1) ------------------------------------

    def update(self, content) -> None:  # type: ignore[override]
        """Forward to the banner Static — preserved for tests that call
        update() directly with a single Rich Text payload. The pane
        treats this as override mode."""
        self._mode = "override"
        self._banner.update(content)
        self._hide_sections()
        self._banner.styles.display = "block"
        self.scroll_home(animate=False)

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.border_title = t(self.lang, "detail_title")
        # Re-render the breadcrumb in the new language without waiting
        # for the next App-triggered refresh — the strings inside are
        # localized, and the App's refresh_state() will follow shortly
        # for the body content.
        kind, args = self._breadcrumb_state
        self._render_breadcrumb(kind, **args)
        # The current view is in the old language; the App will call
        # update_for_node / show_hint / show_override shortly to refresh.

    def show_hint(self) -> None:
        self._mode = "hint"
        self._override_text = None
        text = Text(t(self.lang, "select_hint"))
        self._banner.update(text)
        self._hide_sections()
        self._banner.styles.display = "block"
        self._render_breadcrumb("hint")
        self.scroll_home(animate=False)

    def show_override(self, title: str, body: str) -> None:
        """Render a tab drill-in payload as a single-text banner."""
        self._mode = "override"
        text = Text(title, style=theme_style("primary", bold=True))
        text.append("\n\n")
        text.append(body)
        self._override_text = text
        self._banner.update(text)
        self._hide_sections()
        self._banner.styles.display = "block"
        self._render_breadcrumb("override", label=title)
        self.scroll_home(animate=False)

    def clear_override(self) -> None:
        self._override_text = None

    def update_for_node(self, graph: GraphSnapshot, node_id: str | None) -> None:
        """Render the active node as a sectioned view."""
        if self._mode == "override" and self._override_text is not None:
            # Tab drill-in payload still owns the pane.
            return
        if node_id is None or graph.node(node_id) is None:
            self.show_hint()
            return
        title, sections = node_detail_sections(graph, node_id, self.lang)
        if not sections:
            self.show_hint()
            return
        self._mode = "node"
        # Title banner: just the short id + kind label, styled like the
        # v4.1 pane so visual continuity holds.
        title_text = Text(title, style=theme_style("primary", bold=True))
        self._banner.update(title_text)
        self._banner.styles.display = "block"
        # Breadcrumb: "from Tree · <node_id>". Phase C: this is the
        # user-facing tell that the Detail pane is reflecting the tree
        # selection (vs a tab drill-in, which goes through show_override
        # and ends up at "drill-in · <label>  ·  Esc to return").
        self._render_breadcrumb("node", target=node_id)
        # Reveal / hide per section.
        seen: set[str] = set()
        for section in sections:
            seen.add(section.key)
            container = self._section_widgets.get(section.key)
            body = self._section_bodies.get(section.key)
            if container is None or body is None:
                continue
            container.title = section.title
            collapsed = self._collapsed_state.get(
                section.key, not section.default_open
            )
            container.collapsed = collapsed
            container.styles.display = "block"
            body.update(section.body)
        for key in SECTION_KEYS:
            if key in seen:
                continue
            container = self._section_widgets.get(key)
            if container is not None:
                container.styles.display = "none"
        self.scroll_home(animate=False)

    # -- section toggle handler -------------------------------------------

    def on_collapsible_toggled(self, event: Collapsible.Toggled) -> None:
        """Fired by Textual when the user clicks/keypresses a section header."""
        container_id = event.collapsible.id or ""
        prefix = "detail-section-"
        if not container_id.startswith(prefix):
            return
        section_key = container_id[len(prefix):]
        callback = self._on_section_toggled
        if callback is None:
            return
        try:
            callback(section_key, bool(event.collapsible.collapsed))
        except Exception:
            # Persistence failures must never block UI; the pane keeps
            # working even if settings can't be written.
            pass

    # -- internals --------------------------------------------------------

    def _hide_sections(self) -> None:
        for container in self._section_widgets.values():
            container.styles.display = "none"

    def _render_breadcrumb(self, kind: str, **args) -> None:
        """Update the top breadcrumb Static for the current view mode.

        ``kind`` is one of ``"hint"``, ``"node"``, ``"override"``. The
        ``args`` carry the kind-specific format values (``target`` for
        node mode, ``label`` for override mode). The pane caches the
        last call so :meth:`set_language` can re-render without the
        App needing to re-push values.
        """
        self._breadcrumb_state = (kind, dict(args))
        from cockpit.theme import color as _color

        if kind == "hint":
            text = Text(
                t(self.lang, "breadcrumb_hint"),
                style=_color("foreground-subtle"),
            )
        elif kind == "override":
            label = str(args.get("label", "")).strip() or "?"
            text = Text(
                t(self.lang, "breadcrumb_override", label=label),
                style=_color("warning"),
            )
        else:  # node
            target = str(args.get("target", "")).strip() or "?"
            source = t(self.lang, "source_tree")
            text = Text(
                t(self.lang, "breadcrumb_node", source=source, target=target),
                style=_color("foreground-muted"),
            )
        self._breadcrumb.update(text)

    # Kept for backwards compatibility with the v4.1.0a4 visual-polish
    # tests that still call this directly.
    def _bt_line(self, node: GraphNode) -> str | None:
        from cockpit.details import _bt_line as _impl

        return _impl(node)
