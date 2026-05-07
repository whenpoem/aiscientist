"""Detail pane for the cockpit TUI."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from cockpit.data import GraphSnapshot
from cockpit.i18n import kind_label, state_label, t
from cockpit.theme import style as theme_style


class NodeDetailPane(Static):
    """Render the selected node or a temporary override."""

    def __init__(self) -> None:
        super().__init__("")
        self.id = "detail-pane"
        self.classes = "pane"
        self.lang = "en"
        self.border_title = t(self.lang, "detail_title")
        self._override: str | None = None
        self.show_hint()

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
        if self._override is not None:
            return
        node = graph.node(node_id)
        if node is None:
            self.show_hint()
            return
        parents = ", ".join(self._short_id(item) for item in graph.parents_of(node.node_id)) or "-"
        children = ", ".join(
            self._short_id(item) for item in graph.children_of(node.node_id)
        ) or "-"
        cross_edges = graph.cross_edges_of(node.node_id)
        evidence_support = sum(1 for edge in cross_edges if edge["relation"] == "supports")
        evidence_refute = sum(1 for edge in cross_edges if edge["relation"] == "refutes")
        next_action = self._next_action(node.kind, node.state)

        lines = [
            f"{self._short_id(node.node_id)}  {kind_label(self.lang, node.kind)}",
            (
                f"{t(self.lang, 'status')}: {state_label(self.lang, node.state)}  "
                f"{t(self.lang, 'elo')}: {node.elo_score:.1f}"
            ),
            t(
                self.lang,
                "support_refute",
                supports=evidence_support,
                refutes=evidence_refute,
            ),
            f"{t(self.lang, 'next_action')}: {next_action}",
            "",
            f"{t(self.lang, 'node_text')}:",
            node.text,
            "",
            f"{t(self.lang, 'parents')}: {parents}",
            f"{t(self.lang, 'children')}: {children}",
        ]
        if cross_edges:
            lines.append(f"{t(self.lang, 'cross_edges')}:")
            for edge in cross_edges:
                other_id = edge["dst"] if edge["src"] == node.node_id else edge["src"]
                lines.append(f"  -> {self._short_id(other_id)} ({edge['relation']})")
        else:
            lines.append(f"{t(self.lang, 'cross_edges')}: -")
        lines.extend(
            [
                f"{t(self.lang, 'created')}: {node.created_at}",
                f"{t(self.lang, 'created_by')}: {node.created_by}",
            ]
        )
        text = Text(lines[0], style=theme_style("primary", bold=True))
        for line in lines[1:]:
            text.append("\n")
            text.append(line)
        self.update(text)

    def _next_action(self, kind: str, state: str) -> str:
        if state == "refuted":
            return t(self.lang, "next_refuted")
        if kind == "evidence":
            return t(self.lang, "next_evidence")
        if kind == "hypothesis":
            return t(self.lang, "next_hypothesis")
        return "-"

    @staticmethod
    def _short_id(node_id: str) -> str:
        if "_" not in node_id:
            return node_id[:10]
        prefix, suffix = node_id.split("_", 1)
        return f"{prefix}_{suffix[:4]}"
