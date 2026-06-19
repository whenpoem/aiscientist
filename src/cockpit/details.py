"""Detail-text builders shared between the main-screen detail pane and the
full-screen DetailScreen overlay.

Each builder takes a domain object plus a language and returns either a
``(title: str, body: Text | str)`` tuple (legacy callers) or a list of
``DetailSection`` rows (v4.2.0a1 callers that want collapsible sections).

The section-based API is the primary form going forward; ``node_detail_text``
is preserved as a shim that joins every section's title + body into the
single Rich Text the v4.1 panes consumed. Tests using ``node_detail_text``
continue to work without modification.

Originally these formatters lived inside ``NodeDetailPane.update_for_node``
and ``CockpitApp._row_detail``. Pulling them out into free functions lets
the DetailScreen consume the exact same output without duplicating logic
and without inheriting from a widget class. It also makes the formatters
trivially unit-testable — no Textual lifecycle required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from rich.text import Text

from cockpit.bars import strength_bar
from cockpit.data import GraphNode, GraphSnapshot
from cockpit.i18n import kind_label, state_label, t


@dataclass(frozen=True)
class DetailSection:
    """One collapsible region of the node-detail view.

    Sections are ordered; the cockpit's detail pane renders them in
    declaration order, top to bottom. ``key`` is a stable short id used
    for persistence (which sections were collapsed last session) and
    for test assertions. ``title`` is the localized header text shown
    on the collapsible header bar. ``body`` is the Rich Text rendered
    inside the section when expanded. ``default_open`` controls the
    initial collapsed state for users who have no persisted preference.
    ``empty`` flags sections that have nothing meaningful to display
    (no children, no failures, etc.) so the pane can drop them out
    rather than render a row of dashes.
    """

    key: str
    title: str
    body: Text
    default_open: bool = True
    empty: bool = False

    def with_body(self, body: Text) -> "DetailSection":
        """Return a copy with a replaced body — used by tests / shims."""
        return DetailSection(
            key=self.key,
            title=self.title,
            body=body,
            default_open=self.default_open,
            empty=self.empty,
        )


# Stable ordering used by the detail pane to allocate one Collapsible
# slot per section key. The pane pre-allocates all keys; sections that
# return ``empty=True`` (or are absent from the builder output) hide
# their slot. New section keys go at the end so v4.2.x users don't get
# their persisted collapsed-state shuffled around.
SECTION_KEYS: tuple[str, ...] = (
    "overview",
    "bt",
    "children",
    "cross_edges",
    "failures",
    "reports",
)


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


def _join_lines(lines: list[str]) -> Text:
    """Render a list of plain strings as a single Rich Text with newlines."""
    if not lines:
        return Text("")
    body = Text(lines[0])
    for line in lines[1:]:
        body.append("\n")
        body.append(line)
    return body


def node_detail_sections(
    graph: GraphSnapshot, node_id: str, lang: str
) -> tuple[str, list[DetailSection]]:
    """Render a node as an ordered list of collapsible sections.

    Returns ``(title, [sections...])``. The title carries the short
    node id + localized kind label (e.g. ``"H_a3f1  Hypothesis"``);
    section bodies carry the contents per section key. When the node
    id is unknown, returns ``("", [])`` so callers can fall back to a
    generic empty-state hint.
    """
    node = graph.node(node_id)
    if node is None:
        return ("", [])
    parents = (
        ", ".join(short_id(item) for item in graph.parents_of(node.node_id))
        or "-"
    )
    children_ids = list(graph.children_of(node.node_id))
    cross_edges = graph.cross_edges_of(node.node_id)
    evidence_support = sum(1 for edge in cross_edges if edge["relation"] == "supports")
    evidence_refute = sum(1 for edge in cross_edges if edge["relation"] == "refutes")

    title = f"{short_id(node.node_id)}  {kind_label(lang, node.kind)}"

    # ---- overview ------------------------------------------------------
    overview_lines = [
        f"{t(lang, 'status')}: {state_label(lang, node.state)}",
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
        f"{t(lang, 'created')}: {node.created_at}",
        f"{t(lang, 'created_by')}: {node.created_by}",
    ]
    sections: list[DetailSection] = [
        DetailSection(
            key="overview",
            title=t(lang, "detail_section_overview"),
            body=_join_lines(overview_lines),
            default_open=True,
        )
    ]

    # ---- bt ------------------------------------------------------------
    bt = _bt_line(node)
    if bt:
        sections.append(
            DetailSection(
                key="bt",
                title=t(lang, "detail_section_bt"),
                body=Text(bt),
                default_open=True,
            )
        )

    # ---- children ------------------------------------------------------
    if children_ids:
        child_lines = [f"  -> {short_id(item)}" for item in children_ids]
        sections.append(
            DetailSection(
                key="children",
                title=t(
                    lang,
                    "detail_section_children",
                    count=len(children_ids),
                ),
                body=_join_lines(child_lines),
                default_open=False,
            )
        )

    # ---- cross_edges ---------------------------------------------------
    if cross_edges:
        edge_lines: list[str] = []
        for edge in cross_edges:
            other_id = edge["dst"] if edge["src"] == node.node_id else edge["src"]
            edge_lines.append(
                f"  -> {short_id(other_id)} ({edge['relation']})"
            )
        sections.append(
            DetailSection(
                key="cross_edges",
                title=t(
                    lang,
                    "detail_section_cross_edges",
                    count=len(cross_edges),
                ),
                body=_join_lines(edge_lines),
                default_open=False,
            )
        )

    # ---- reports (v4.2.0a2 / ADR 0009) ---------------------------------
    # Surface generated report files associated with this node. Reading
    # cockpit_reports here avoids a second query path; if the table
    # doesn't exist (legacy DB) we silently skip the section.
    related_reports = _fetch_related_reports(node.node_id)
    if related_reports:
        report_lines = [
            f"  - [{row['format']}] {row['file_path']}"
            + (
                "  (missing)"
                if row.get("missing")
                else f"  ({row['generated_at']})"
            )
            for row in related_reports
        ]
        sections.append(
            DetailSection(
                key="reports",
                title=t(
                    lang,
                    "detail_section_reports",
                    count=len(related_reports),
                ),
                body=_join_lines(report_lines),
                default_open=False,
            )
        )

    return (title, sections)


def _fetch_related_reports(node_id: str) -> list[dict]:
    """Read cockpit_reports rows pointing at ``node_id``.

    Best-effort: returns an empty list when the table doesn't exist
    yet or when SQLite trips on a transient race. The detail pane is
    a display surface, not a write path, so we lean toward "show
    nothing" over "show error toast".
    """
    try:
        from cockpit.data import fetch_reports
    except Exception:  # pragma: no cover - defensive
        return []
    try:
        rows = fetch_reports(limit=50)
    except Exception:  # pragma: no cover - defensive
        return []
    return [row for row in rows if row.get("related_node_id") == node_id]


def node_detail_text(
    graph: GraphSnapshot, node_id: str, lang: str
) -> tuple[str, Text]:
    """Legacy single-Text view of a node.

    Joins every section's title + body into one Rich Text. Preserved
    for callers that want the un-sectioned form (the DetailScreen
    drill-in's sibling-navigation breadcrumb, tests, the export
    module's plain-text rendering). The v4.2 detail pane uses
    ``node_detail_sections`` directly.

    Returns ``("", hint)`` when the node id is unknown so callers can
    fall back to a generic empty state.
    """
    node = graph.node(node_id)
    if node is None:
        return ("", Text(t(lang, "select_hint")))
    title, sections = node_detail_sections(graph, node_id, lang)
    if not sections:
        return (title, Text(""))
    body = Text()
    for idx, section in enumerate(sections):
        if idx > 0:
            body.append("\n\n")
            body.append(section.title)
            body.append("\n")
        body.append(section.body)
    return (title, body)


def event_detail_text(row: dict, lang: str) -> tuple[str, str]:
    """Format a single ``cockpit_events`` row for the DetailScreen.

    The body is a plain string with the JSON payload pretty-printed so
    the user can scan structured fields without scrolling a single dense
    line. We keep this in plain str (not Rich Text) because the JSON
    indentation already conveys hierarchy and styling would compete.

    Phase E: surfaces the row's ``source`` column (provenance tag) as
    an "emitted by" line. Old rows (pre-v4 schema or pre-Phase-E
    callers) carry ``NULL`` and render as the localized
    ``provenance_unknown`` label.
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
    source_label = provenance_label(row.get("source"), lang)
    title = f"{t(lang, 'event_drill_title', kind=kind)}"
    body_lines = [
        f"id: {row.get('id', '-')}",
        f"{t(lang, 'created')}: {created}",
        f"{t(lang, 'event_source')}: {source_label}",
        "",
        f"{t(lang, 'event_payload')}:",
        payload_str,
    ]
    return (title, "\n".join(body_lines))


def provenance_label(raw_source, lang: str) -> str:
    """Translate a raw ``cockpit_events.source`` value into UI text.

    Known values get a localized friendly label; anything else (a new
    source string from a future MCP server, or a hand-edited DB row)
    is echoed as-is so it still conveys *some* information.
    ``None`` / empty → the localized ``provenance_unknown`` placeholder.
    """
    if not raw_source:
        return t(lang, "provenance_unknown")
    key = f"provenance_{raw_source}"
    label = t(lang, key)
    # ``cockpit.i18n.t`` returns the key unchanged when no translation
    # exists — that's the signal to fall back to the raw value.
    if label == key:
        return str(raw_source)
    return label
