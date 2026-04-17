"""Detail pane for the cockpit TUI."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from cockpit.data import GraphSnapshot


class NodeDetailPane(Static):
    """Render the selected node or a temporary override."""

    def __init__(self) -> None:
        super().__init__("")
        self.id = "detail-pane"
        self.classes = "pane"
        self.border_title = "2 Node Detail"
        self._override: str | None = None
        self.show_hint()

    def show_hint(self) -> None:
        self._override = None
        self.update("Select a hypothesis with j/k or click.")

    def show_override(self, title: str, body: str) -> None:
        self._override = body
        text = Text(title, style="bold #58a6ff")
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
        parents = ", ".join(graph.parents_of(node.node_id)) or "-"
        children = ", ".join(graph.children_of(node.node_id)) or "-"
        cross_edges = graph.cross_edges_of(node.node_id)
        evidence_support = sum(1 for edge in cross_edges if edge["relation"] == "supports")
        evidence_refute = sum(1 for edge in cross_edges if edge["relation"] == "refutes")

        lines = [
            f"{node.node_id}  {node.kind}  state: {node.state}  elo: {node.elo_score:.1f}",
            "",
            node.text,
            "",
            f"Parents: {parents}",
            f"Children: {children}",
        ]
        if cross_edges:
            lines.append("Cross-edges:")
            for edge in cross_edges:
                other_id = edge["dst"] if edge["src"] == node.node_id else edge["src"]
                lines.append(f"  -> {other_id} ({edge['relation']})")
        else:
            lines.append("Cross-edges: -")
        lines.extend(
            [
                f"Evidence: {evidence_support} supports / {evidence_refute} refutes",
                f"Created: {node.created_at}",
                f"Created by: {node.created_by}",
            ]
        )
        text = Text(lines[0], style="bold #58a6ff")
        for line in lines[1:]:
            text.append("\n")
            text.append(line)
        self.update(text)
