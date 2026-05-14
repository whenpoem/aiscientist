"""Tree pane for the cockpit TUI."""

from __future__ import annotations

from functools import lru_cache

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Tree

from cockpit.data import GraphNode, GraphSnapshot
from cockpit.i18n import REFUTED_ICON, kind_icon, t
from cockpit.theme import color, kind_color


class HypothesisTreePane(Tree[str]):
    """Navigation tree for hypotheses, evidence, and related nodes."""

    # Pane-scoped binding (v4.2.0a1 / A3): ``i`` toggles compact mode on
    # this pane only. The rest of the cockpit ignores ``i`` — see
    # docs/cockpit-keys.md for the canonical scope map.
    BINDINGS = [
        Binding("i", "toggle_compact", "Tree info"),
    ]

    def __init__(self, *, compact: bool = True) -> None:
        super().__init__("research")
        self.id = "tree-pane"
        self.classes = "pane"
        self.lang = "en"
        self.border_title = t(self.lang, "tree_title")
        self.show_root = False
        self.auto_expand = False
        self.node_lookup: dict[str, object] = {}
        self._visible_ids: list[str] = []
        # When True, _label_for omits BT/Elo suffix so node text owns the
        # column. The detail pane still shows the full stats so nothing is
        # hidden — it's a relocation, not a removal.
        self._compact = compact
        # Latest counts for border title rendering. Updated via
        # set_counts(); falls back to None until first refresh.
        self._counts: dict[str, int] | None = None
        # Phase E3: set of bookmarked node ids. Updated via set_bookmarks
        # whenever the App's settings list changes (i.e. on every ``b``
        # toggle). Stored as a set for O(1) membership test in _label_for.
        self._bookmarks: set[str] = set()

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.set_title()

    def current_node_id(self) -> str | None:
        cursor = self.cursor_node
        data = getattr(cursor, "data", None)
        return data if isinstance(data, str) else None

    def visible_node_ids(self) -> list[str]:
        return list(self._visible_ids)

    def move_cursor_by(self, delta: int) -> None:
        if delta > 0:
            for _ in range(delta):
                self.action_cursor_down()
        elif delta < 0:
            for _ in range(abs(delta)):
                self.action_cursor_up()

    def move_cursor_to_top(self) -> None:
        if self._visible_ids:
            self.select_node_id(self._visible_ids[0])

    def move_cursor_to_bottom(self) -> None:
        if self._visible_ids:
            self.select_node_id(self._visible_ids[-1])

    def select_node_id(self, node_id: str | None) -> None:
        if node_id and node_id in self.node_lookup:
            self.select_node(self.node_lookup[node_id])

    def expand_current(self) -> None:
        cursor = self.cursor_node
        if cursor is not None:
            cursor.expand()

    def collapse_current(self) -> None:
        cursor = self.cursor_node
        if cursor is not None:
            cursor.collapse()

    def set_compact(self, compact: bool) -> None:
        """Toggle BT/Elo suffix in tree labels. Triggers a full reload so
        existing rows redraw with the new style; relies on the caller to
        pass the current GraphSnapshot via load_graph afterwards."""
        self._compact = bool(compact)

    def set_bookmarks(self, bookmarks) -> None:
        """Phase E3: inject the latest bookmark set.

        The App calls this from ``_refresh_graph`` so the pane stays in
        lockstep with settings.bookmarks. Accepts any iterable of str
        for convenience; coerces to a set internally for fast lookup.
        """
        try:
            self._bookmarks = {str(b) for b in (bookmarks or []) if b}
        except TypeError:  # pragma: no cover - defensive
            self._bookmarks = set()

    def action_toggle_compact(self) -> None:
        """Pane-scoped compact toggle.

        Delegates to the App's action so persistence and the global
        re-render still happen; the pane class owns the binding so the
        keystroke only fires when the tree pane has focus.
        """
        try:
            self.app.action_toggle_tree_compact()  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive
            pass

    def set_counts(self, counts: dict[str, int] | None) -> None:
        """Stash the latest summary counts AND repaint the border title.

        ``counts`` keys map to i18n format args of ``tree_count_suffix``
        (active / refuted). Called from app._refresh_counts after the
        dashboard summary lands, so the title stays in lockstep with the
        status bar even if _refresh_graph already redrew the title with
        stale counts earlier in the same refresh cycle.
        """
        self._counts = dict(counts) if counts else None
        # Preserve the active filter — _pane_filters["tree"] is the source
        # of truth in the App; the tree pane only knows what was last
        # passed through set_title, which we don't want to reset to "".
        # An empty arg here means "use cached state"; the App passes the
        # current filter explicitly when it calls set_title from load_graph.
        if self.is_mounted:
            current = self.border_title or ""
            # Re-derive filter from the existing border_title if present
            # (the title format is "<name> (filter: ...)"). This avoids
            # threading a filter argument through set_counts callers.
            from cockpit.i18n import t as _t
            filter_marker = _t(self.lang, "filter_suffix", value="")
            # filter_marker is e.g. "filter: " — if the title contains it,
            # the user is filtering and we leave the title alone.
            if filter_marker.strip(":") in current:
                return
            self.set_title("")

    def set_title(self, filter_text: str = "") -> None:
        # Filter takes precedence — the user actively narrowed the view, so
        # showing counts AND a filter blurb would crowd the border title.
        if filter_text:
            suffix = f" ({t(self.lang, 'filter_suffix', value=filter_text)})"
        elif self._counts:
            suffix = " · " + t(
                self.lang,
                "tree_count_suffix",
                active=self._counts.get("active", 0),
                refuted=self._counts.get("refuted", 0),
            )
        else:
            suffix = ""
        self.border_title = f"{t(self.lang, 'tree_title')}{suffix}"

    def load_graph(
        self,
        graph: GraphSnapshot,
        *,
        show_refuted: bool,
        filter_text: str = "",
        selected_node_id: str | None = None,
    ) -> str | None:
        expanded_ids = {
            node_id
            for node_id, tree_node in self.node_lookup.items()
            if getattr(tree_node, "is_expanded", False)
        }
        self.node_lookup.clear()
        self._visible_ids.clear()
        self.root.remove_children()
        self.root.expand()
        self.set_title(filter_text)

        needle = filter_text.strip().lower()

        @lru_cache(maxsize=None)
        def matches(node_id: str) -> bool:
            node = graph.node(node_id)
            if node is None:
                return False
            if not needle:
                return True
            haystack = f"{node.node_id} {node.kind} {node.text}".lower()
            if needle in haystack:
                return True
            return any(matches(child_id) for child_id in graph.children_of(node_id))

        def visible_children(node_id: str) -> list[str]:
            children: list[str] = []
            for child_id in graph.children_of(node_id):
                node = graph.node(child_id)
                if node is None or not matches(child_id):
                    continue
                if node.state == "refuted" and not show_refuted:
                    children.extend(visible_children(child_id))
                    continue
                children.append(child_id)
            return children

        def add_branch(parent_ui_node, node_id: str) -> None:
            node = graph.node(node_id)
            if node is None:
                return
            child_ids = visible_children(node_id)
            ui_node = parent_ui_node.add(
                self._label_for(node),
                data=node_id,
                expand=(node_id in expanded_ids or bool(needle)),
                allow_expand=bool(child_ids),
            )
            self.node_lookup[node_id] = ui_node
            self._visible_ids.append(node_id)
            for child_id in child_ids:
                add_branch(ui_node, child_id)

        root_ids: list[str] = []
        for root_id in graph.roots:
            node = graph.node(root_id)
            if node is None or not matches(root_id):
                continue
            if node.state == "refuted" and not show_refuted:
                root_ids.extend(visible_children(root_id))
            else:
                root_ids.append(root_id)
        for root_id in root_ids:
            add_branch(self.root, root_id)

        if not self._visible_ids:
            self.root.add_leaf(t(self.lang, "no_hypotheses"))
            return None

        if selected_node_id in self.node_lookup:
            candidate = selected_node_id
        else:
            candidate = self._visible_ids[0]
        self.select_node_id(candidate)
        return self.current_node_id()

    def _label_for(self, node: GraphNode) -> Text:
        title = Text()
        # Phase E3: bookmark indicator. Prepends a filled four-pointed
        # star ``✦`` to the row when the node has been bookmarked by
        # the user. The glyph was picked deliberately disjoint from the
        # kind / phase / family / severity axes — see
        # tests/cockpit/test_glyph_axes.py for the disjointness
        # guarantee. Uses the ``warning`` color tier so the bookmark
        # reads as a deliberate "user mark" rather than a state cue.
        if node.node_id in self._bookmarks:
            title.append("✦ ", style=color("warning"))
        title.append(self._prefix_for(node), style=self._style_for(node))
        title.append(" ")
        title.append(self._short_id(node.node_id), style=self._style_for(node))
        title.append(" ")
        title.append(node.text)
        # In compact mode (default) the BT/Elo numerics live in the detail
        # pane, freeing column width for node text. The `i` key flips this
        # back for power-user scanning.
        if not self._compact:
            if node.kind == "hypothesis":
                title.append(self._bt_suffix(node), style="dim")
                title.append(f"  elo {node.elo_score:.0f}", style="dim")
            elif node.kind == "proof_skeleton":
                title.append(self._bt_suffix(node), style="dim")
        if node.bt_status == "paused":
            title.append("  [paused]", style=color("warning"))
        if node.state == "refuted":
            title.stylize("strike")
        return title

    @staticmethod
    def _bt_suffix(node: GraphNode) -> str:
        if node.bt_strength is None or node.bt_n_comparisons <= 0:
            return "  bt n/a"
        import math

        sd = math.sqrt(max(1e-6, float(node.bt_strength_var or 1.0)))
        return (
            f"  bt {node.bt_strength:+.2f}±{1.96*sd:.2f}"
            f" n={node.bt_n_comparisons}"
        )

    @staticmethod
    def _short_id(node_id: str) -> str:
        if "_" not in node_id:
            return node_id[:10]
        prefix, suffix = node_id.split("_", 1)
        return f"{prefix}_{suffix[:4]}"

    @staticmethod
    def _prefix_for(node: GraphNode) -> str:
        # Refuted overrides kind so a struck-through line is unmistakable
        # even if the user rebinds kind glyphs in a future custom theme.
        if node.state == "refuted":
            return REFUTED_ICON
        return kind_icon(node.kind)

    @staticmethod
    def _style_for(node: GraphNode) -> str:
        # Theme-aware coloring. The token names match the kind keys 1:1
        # (with underscore→hyphen) so adding a new node kind just requires a
        # matching `kind-<new-kind>` entry in src/cockpit/theme/themes.py.
        if node.state == "refuted":
            return color("kind-refuted")
        return kind_color(node.kind)
