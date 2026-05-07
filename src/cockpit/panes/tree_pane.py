"""Tree pane for the cockpit TUI."""

from __future__ import annotations

from functools import lru_cache

from rich.text import Text
from textual.widgets import Tree

from cockpit.data import GraphNode, GraphSnapshot
from cockpit.i18n import t


class HypothesisTreePane(Tree[str]):
    """Navigation tree for hypotheses, evidence, and related nodes."""

    def __init__(self) -> None:
        super().__init__("research")
        self.id = "tree-pane"
        self.classes = "pane"
        self.lang = "en"
        self.border_title = t(self.lang, "tree_title")
        self.show_root = False
        self.auto_expand = False
        self.node_lookup: dict[str, object] = {}
        self._visible_ids: list[str] = []

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

    def set_title(self, filter_text: str = "") -> None:
        suffix = (
            f" ({t(self.lang, 'filter_suffix', value=filter_text)})"
            if filter_text
            else ""
        )
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
        title.append(self._prefix_for(node), style=self._style_for(node))
        title.append(" ")
        title.append(self._short_id(node.node_id), style=self._style_for(node))
        title.append(" ")
        title.append(node.text)
        if node.kind == "hypothesis":
            title.append(self._bt_suffix(node), style="dim")
            title.append(f"  elo {node.elo_score:.0f}", style="dim")
        elif node.kind == "proof_skeleton":
            title.append(self._bt_suffix(node), style="dim")
        if node.bt_status == "paused":
            title.append("  [paused]", style="#d29922")
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
        if node.state == "refuted":
            return "X"
        return {
            "question": "Q",
            "hypothesis": "H",
            "experiment": "E",
            "evidence": "EV",
            "conclusion": "C",
            # Proof trunk kinds (architecture.md §13)
            "proposition": "T",
            "proof_skeleton": "PS",
            "proof_snippet": "ps",
        }.get(node.kind, "-")

    @staticmethod
    def _style_for(node: GraphNode) -> str:
        if node.state == "refuted":
            return "#f85149"
        return {
            "question": "#79c0ff",
            "hypothesis": "#58a6ff",
            "experiment": "#d29922",
            "evidence": "#3fb950",
            "conclusion": "#bc8cff",
            # Proof trunk: amber-ish so it visually pairs with experiment
            # without colliding with hypothesis blue.
            "proposition": "#e3b341",
            "proof_skeleton": "#d29922",
            "proof_snippet": "#a98012",
        }.get(node.kind, "#c9d1d9")
