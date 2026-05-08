"""Detail-text builders shared between the main-screen detail pane and the
full-screen DetailScreen overlay.

Each builder takes a domain object plus a language and returns a
``(title: str, body: Text | str)`` tuple. The main detail pane renders
these in a narrow column; the DetailScreen renders them in the full
window with sibling navigation.

Originally these formatters lived inside ``NodeDetailPane.update_for_node``
and ``CockpitApp._row_detail``. Pulling them out into free functions lets
the new DetailScreen consume the exact same output without duplicating
logic and without inheriting from a widget class. It also makes the
formatters trivially unit-testable — no Textual lifecycle required.
"""

from __future__ import annotations

import json

from rich.text import Text

from cockpit.bars import strength_bar
from cockpit.data import GraphNode, GraphSnapshot
from cockpit.i18n import kind_label, state_label, t


def short_id(node_id: str) -> str:
    """Format ``H_a3f1c2`` → ``H_a3f1`` for compact title text."""
    if "_" not in node_id:
        return node_id[:10]
    prefix, suffix = node_id.split("_", 1)
    return f"{prefix}_{suffix[:4]}"


def _bt_line(node: GraphNode) -> str | None:
    """Render the BT strength line, or None when the node has no rating.

    Hypothesis and proof_skeleton are the only kinds the BT tournament
    ranks; for everything else we omit the line so the detail pane
    doesn't carry a "bt n/a" placeholder.
    """
    if node.kind not in ("hypothesis", "proof_skeleton"):
        return None
    if node.bt_strength is None or node.bt_n_comparisons <= 0:
        return "bt: -  n=0"
    import math

    sd = math.sqrt(max(1e-6, float(node.bt_strength_var or 1.0)))
    ci = 1.96 * sd
    bar = strength_bar(float(node.bt_strength))
    return (
        f"bt: {node.bt_strength:+.2f} "
        f"[{bar}] ±{ci:.2f}  n={node.bt_n_comparisons}"
    )


def _next_action(lang: str, kind: str, state: str) -> str:
    if state == "refuted":
        return t(lang, "next_refuted")
    if kind == "evidence":
        return t(lang, "next_evidence")
    if kind == "hypothesis":
        return t(lang, "next_hypothesis")
    return "-"


def node_detail_text(
    graph: GraphSnapshot, node_id: str, lang: str
) -> tuple[str, Text]:
    """Render the full body of a graph node — used by the main detail pane
    and the DetailScreen drill-in alike. Returns ``("", hint)`` when the
    node id is unknown so callers can fall back to a generic empty state."""
    node = graph.node(node_id)
    if node is None:
        return ("", Text(t(lang, "select_hint")))
    parents = (
        ", ".join(short_id(item) for item in graph.parents_of(node.node_id))
        or "-"
    )
    children = (
        ", ".join(short_id(item) for item in graph.children_of(node.node_id))
        or "-"
    )
    cross_edges = graph.cross_edges_of(node.node_id)
    evidence_support = sum(1 for edge in cross_edges if edge["relation"] == "supports")
    evidence_refute = sum(1 for edge in cross_edges if edge["relation"] == "refutes")

    title = f"{short_id(node.node_id)}  {kind_label(lang, node.kind)}"
    lines: list[str] = [
        (
            f"{t(lang, 'status')}: {state_label(lang, node.state)}  "
            f"{t(lang, 'elo')}: {node.elo_score:.1f}"
        ),
    ]
    bt = _bt_line(node)
    if bt:
        lines.append(bt)
    lines.extend(
        [
            t(
                lang,
                "support_refute",
                supports=evidence_support,
                refutes=evidence_refute,
            ),
            f"{t(lang, 'next_action')}: {_next_action(lang, node.kind, node.state)}",
            "",
            f"{t(lang, 'node_text')}:",
            node.text,
            "",
            f"{t(lang, 'parents')}: {parents}",
            f"{t(lang, 'children')}: {children}",
        ]
    )
    if cross_edges:
        lines.append(f"{t(lang, 'cross_edges')}:")
        for edge in cross_edges:
            other_id = edge["dst"] if edge["src"] == node.node_id else edge["src"]
            lines.append(f"  -> {short_id(other_id)} ({edge['relation']})")
    else:
        lines.append(f"{t(lang, 'cross_edges')}: -")
    lines.extend(
        [
            f"{t(lang, 'created')}: {node.created_at}",
            f"{t(lang, 'created_by')}: {node.created_by}",
        ]
    )

    body = Text(lines[0])
    for line in lines[1:]:
        body.append("\n")
        body.append(line)
    return (title, body)


def event_detail_text(row: dict, lang: str) -> tuple[str, str]:
    """Format a single ``cockpit_events`` row for the DetailScreen.

    The body is a plain string with the JSON payload pretty-printed so
    the user can scan structured fields without scrolling a single dense
    line. We keep this in plain str (not Rich Text) because the JSON
    indentation already conveys hierarchy and styling would compete.
    """
    kind = str(row.get("kind", "event"))
    created = str(row.get("created_at", ""))
    payload = row.get("payload")
    if isinstance(payload, dict):
        payload_str = json.dumps(payload, indent=2, ensure_ascii=False)
    elif payload is None:
        payload_str = "-"
    else:
        payload_str = str(payload)
    title = f"{t(lang, 'event_drill_title', kind=kind)}"
    body_lines = [
        f"id: {row.get('id', '-')}",
        f"{t(lang, 'created')}: {created}",
        "",
        f"{t(lang, 'event_payload')}:",
        payload_str,
    ]
    return (title, "\n".join(body_lines))
