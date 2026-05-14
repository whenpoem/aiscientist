"""Right-side tabbed tables for the cockpit TUI.

Tabs are organized into three groups (v4.2.0a1):

- ``cross``     — usable from either trunk (risks, claims, literature)
- ``empirical`` — ML-experiment workflow only (failures)
- ``proof``     — proof-trunk only (corpus, diagnostics, lean)

The ``f`` key cycles tabs within the active group; ``shift+f`` jumps to
the first tab of the next group. The grouping makes the ``f`` walk feel
predictable when the tab count grows past what an "all in one ring"
cycle can navigate comfortably.

The three proof-trunk tabs render empty-state hints when their tables are
absent (v3.x DB) or empty (fresh install pre-seed-corpus). All cells go
through ``cockpit.i18n.t`` so the bilingual contract holds.
"""

from __future__ import annotations

from textual.containers import Container
from textual.widgets import DataTable, Static

from cockpit.i18n import t


def _truncate(value: str, max_width: int) -> str:
    """Truncate to ``max_width`` and append a typographic ellipsis when cut.

    The typographic ``…`` (U+2026) is one cell and renders consistently on
    every terminal we target; the previous ASCII ``...`` ate three cells
    and looked like a stuttered word. Drill-in (Enter on the row) is the
    user-facing recovery for the elided suffix.
    """
    if max_width <= 0 or len(value) <= max_width:
        return value
    return value[: max(0, max_width - 1)] + "…"


# Tab grouping (v4.2.0a1 / A1). The order of TAB_GROUPS defines:
#   - the visual left-to-right order of group chips
#   - the order shift+f walks through groups
#   - the within-group cycle order under plain f
# TAB_ORDER is the flat sequence used by the rest of the codebase (drill-in
# routing, _filtered_rows keys); it is kept as the canonical flat list so
# pre-grouping callers stay unchanged.
TAB_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # ``focus`` is the v5.0 leading tab: derived live from
    # cockpit_events, populated by cockpit.panes.focus_pane.derive_focus.
    # Listed first so a user pressing ``4`` lands on the most-relevant
    # tab for "what is the agent doing right now".
    ("cross", ("focus", "risks", "claims", "literature", "reports")),
    ("empirical", ("failures",)),
    ("proof", ("corpus", "diagnostics", "lean")),
)
TAB_ORDER: tuple[str, ...] = tuple(
    name for _group, names in TAB_GROUPS for name in names
)
TAB_GROUP_OF: dict[str, str] = {
    name: group for group, names in TAB_GROUPS for name in names
}
TABLE_IDS = {
    "focus": "focus-table",
    "risks": "risks-table",
    "failures": "failures-table",
    "claims": "claims-table",
    "literature": "literature-table",
    "reports": "reports-table",
    "corpus": "corpus-table",
    "diagnostics": "diagnostics-table",
    "lean": "lean-table",
}


def group_of(tab_name: str) -> str:
    """Return the group key (``cross``/``empirical``/``proof``) for a tab.

    Falls back to the first group's key when the tab name is unknown — that
    keeps the cockpit from crashing on a stale settings file pointing at a
    removed tab.
    """
    return TAB_GROUP_OF.get(tab_name, TAB_GROUPS[0][0])


def tabs_in_group(group_key: str) -> tuple[str, ...]:
    """Return the tabs in ``group_key`` in their canonical order."""
    for key, names in TAB_GROUPS:
        if key == group_key:
            return names
    return ()


def next_tab_in_group(active: str) -> str:
    """Advance to the next tab inside the active tab's group, wrapping."""
    group = group_of(active)
    names = tabs_in_group(group)
    if not names:
        return active
    if active not in names:
        return names[0]
    idx = names.index(active)
    return names[(idx + 1) % len(names)]


def next_group(active: str) -> str:
    """Return the first tab of the group that follows ``active``'s group."""
    current = group_of(active)
    group_keys = [g for g, _ in TAB_GROUPS]
    if current not in group_keys:
        return TAB_GROUPS[0][1][0]
    idx = group_keys.index(current)
    next_key = group_keys[(idx + 1) % len(group_keys)]
    return tabs_in_group(next_key)[0]

# Status icons. Keys must stay in sync with the CHECK constraints in
# src/prove_mcp/schema.sql: diagnostic manifests are 'open' / 'empty' /
# 'applied'; Lean attempts are 'queued' / 'running' / 'verified' / 'failed'
# / 'timeout'. Adding a new status here without a schema bump is dead code.
DIAGNOSTIC_STATUS_ICON = {
    "open": "⏳",
    "applied": "✓",
    "empty": "✓",
}
LEAN_STATUS_ICON = {
    "queued": "⏸",
    "running": "▶",
    "verified": "✓",
    "failed": "✗",
    "timeout": "⌛",
}


class RightTabsPane(Container):
    """Risks, failures, claims, literature, and proof-trunk tables."""

    def __init__(self) -> None:
        super().__init__()
        self.id = "tabs-pane"
        self.classes = "pane"
        self.lang = "en"
        # v5.0: ``focus`` is the new leading tab and the safest default
        # to land on — it's derived from cockpit_events so it always
        # has something meaningful, even on a fresh DB (empty-state row).
        self.active = "focus"
        self.border_title = t(self.lang, "tabs_title_all")
        self.focus_rows: list[dict] = []
        self.risks_rows: list[dict] = []
        self.failures_rows: list[dict] = []
        self.claims_rows: list[dict] = []
        self.literature_rows: list[dict] = []
        self.reports_rows: list[dict] = []
        self.corpus_rows: list[dict] = []
        self.diagnostics_rows: list[dict] = []
        self.lean_rows: list[dict] = []
        self._filtered_rows: dict[str, list[dict]] = {key: [] for key in TAB_ORDER}
        self._filter_text = ""

    def compose(self):
        # Group strip sits above the active DataTable. It is a single
        # Static line whose text gets rebuilt every time the active tab
        # changes; only the cell-level styling distinguishes the active
        # group from the others.
        yield Static("", id="tabs-group-bar", classes="tab-group-bar")
        for name in TAB_ORDER:
            yield DataTable(id=TABLE_IDS[name], cursor_type="row", classes="tab-table")

    def on_mount(self) -> None:
        self._configure_tables()
        self._sync_active_table()
        self._refresh_title()
        self._refresh_group_bar()

    def set_language(self, lang: str) -> None:
        self.lang = lang
        if self.is_mounted:
            self._configure_tables()
            self._reload_tables()
        self._refresh_title()
        self._refresh_group_bar()

    def _configure_tables(self) -> None:
        focus = self.query_one(f"#{TABLE_IDS['focus']}", DataTable)
        focus.clear(columns=True)
        focus.add_columns(
            t(self.lang, "focus_col_node"),
            t(self.lang, "focus_col_score"),
            t(self.lang, "focus_col_phase"),
            t(self.lang, "focus_col_intent"),
        )
        risks = self.query_one(f"#{TABLE_IDS['risks']}", DataTable)
        risks.clear(columns=True)
        risks.add_columns(
            t(self.lang, "severity"),
            t(self.lang, "category"),
            t(self.lang, "item"),
            t(self.lang, "summary"),
        )
        failures = self.query_one(f"#{TABLE_IDS['failures']}", DataTable)
        failures.clear(columns=True)
        failures.add_columns(
            t(self.lang, "failure_id"),
            t(self.lang, "trigger"),
            t(self.lang, "symptom"),
            t(self.lang, "seen"),
        )
        claims = self.query_one(f"#{TABLE_IDS['claims']}", DataTable)
        claims.clear(columns=True)
        claims.add_columns(
            t(self.lang, "metric"),
            t(self.lang, "value"),
            t(self.lang, "dataset"),
            t(self.lang, "verified"),
            t(self.lang, "seeds"),
        )
        literature = self.query_one(f"#{TABLE_IDS['literature']}", DataTable)
        literature.clear(columns=True)
        literature.add_columns(
            t(self.lang, "paper_id"),
            t(self.lang, "title"),
            t(self.lang, "year"),
            t(self.lang, "task"),
            t(self.lang, "score"),
        )
        reports = self.query_one(f"#{TABLE_IDS['reports']}", DataTable)
        reports.clear(columns=True)
        reports.add_columns(
            t(self.lang, "reports_col_kind"),
            t(self.lang, "reports_col_node"),
            t(self.lang, "reports_col_format"),
            t(self.lang, "reports_col_size"),
            t(self.lang, "reports_col_time"),
        )
        corpus = self.query_one(f"#{TABLE_IDS['corpus']}", DataTable)
        corpus.clear(columns=True)
        corpus.add_columns(
            t(self.lang, "corpus_col_id"),
            t(self.lang, "corpus_col_domain"),
            t(self.lang, "corpus_col_statement"),
            t(self.lang, "corpus_col_keywords"),
        )
        diagnostics = self.query_one(f"#{TABLE_IDS['diagnostics']}", DataTable)
        diagnostics.clear(columns=True)
        diagnostics.add_columns(
            t(self.lang, "diagnostics_col_manifest"),
            t(self.lang, "diagnostics_col_draft"),
            t(self.lang, "diagnostics_col_status"),
            t(self.lang, "diagnostics_col_snippets"),
            t(self.lang, "diagnostics_col_flawed"),
        )
        lean = self.query_one(f"#{TABLE_IDS['lean']}", DataTable)
        lean.clear(columns=True)
        lean.add_columns(
            t(self.lang, "lean_col_attempt"),
            t(self.lang, "lean_col_proposition"),
            t(self.lang, "lean_col_status"),
            t(self.lang, "lean_col_duration"),
            t(self.lang, "lean_col_triage"),
        )

    def set_filter_text(self, filter_text: str) -> None:
        self._filter_text = filter_text.strip().lower()
        self._reload_tables()

    def set_rows(
        self,
        *,
        risks: list[dict],
        failures: list[dict],
        claims: list[dict],
        literature: list[dict],
        corpus: list[dict] | None = None,
        diagnostics: list[dict] | None = None,
        lean: list[dict] | None = None,
        reports: list[dict] | None = None,
    ) -> None:
        self.risks_rows = list(risks)
        self.failures_rows = list(failures)
        self.claims_rows = list(claims)
        self.literature_rows = list(literature)
        # Optional rows let pre-v4.2 callers keep working without
        # supplying every tab kind on every refresh; the App always
        # passes everything.
        self.corpus_rows = list(corpus or [])
        self.diagnostics_rows = list(diagnostics or [])
        self.lean_rows = list(lean or [])
        self.reports_rows = list(reports or [])
        self._reload_tables()

    def cycle_tab(self) -> None:
        """Advance to the next tab in the active tab's group.

        This is the ``f`` key behavior — the cycle stays inside one
        semantic group at a time so the user knows whether ``f`` will
        move them within "Cross" tabs or "Proof" tabs. To jump across
        groups, the App's ``shift+f`` binding calls ``cycle_group``.
        """
        current = self.active or TAB_ORDER[0]
        self.active = next_tab_in_group(current)
        self._sync_active_table()
        self._refresh_title()
        self._refresh_group_bar()
        self.current_table().focus()

    def cycle_group(self) -> None:
        """Jump to the first tab of the next group (``shift+f`` key)."""
        current = self.active or TAB_ORDER[0]
        self.active = next_group(current)
        self._sync_active_table()
        self._refresh_title()
        self._refresh_group_bar()
        self.current_table().focus()

    def move_cursor_by(self, delta: int) -> None:
        rows = self._filtered_rows.get(self.active or "risks", [])
        if not rows:
            return
        table = self.current_table()
        current = table.cursor_row or 0
        target = max(0, min(len(rows) - 1, current + delta))
        table.move_cursor(row=target, column=0)

    def move_cursor_to_top(self) -> None:
        if self._filtered_rows.get(self.active or "risks"):
            self.current_table().move_cursor(row=0, column=0)

    def move_cursor_to_bottom(self) -> None:
        rows = self._filtered_rows.get(self.active or "risks", [])
        if rows:
            self.current_table().move_cursor(row=len(rows) - 1, column=0)

    def current_row(self) -> dict | None:
        active = self.active or "risks"
        rows = self._filtered_rows.get(active, [])
        if not rows:
            return None
        row_index = self.current_table().cursor_row or 0
        if row_index >= len(rows):
            return None
        return rows[row_index]

    def current_table(self) -> DataTable:
        active = self.active or "risks"
        return self.query_one(f"#{TABLE_IDS[active]}", DataTable)

    def _reload_tables(self) -> None:
        payloads = {
            "focus": self.focus_rows,
            "risks": self.risks_rows,
            "failures": self.failures_rows,
            "claims": self.claims_rows,
            "literature": self.literature_rows,
            "reports": self.reports_rows,
            "corpus": self.corpus_rows,
            "diagnostics": self.diagnostics_rows,
            "lean": self.lean_rows,
        }
        self._filtered_rows = {
            name: self._filter_rows(rows) for name, rows in payloads.items()
        }
        self._reload_focus_table()
        self._reload_risks_table()
        self._reload_failure_table()
        self._reload_claims_table()
        self._reload_literature_table()
        self._reload_reports_table()
        self._reload_corpus_table()
        self._reload_diagnostics_table()
        self._reload_lean_table()
        self._sync_active_table()
        self._refresh_title()

    def update_focus(self, state) -> None:
        """v5.0: replace the Focus tab rows from a derived ``FocusState``.

        Empties to a single hint row when ``state.nodes`` is empty so
        the tab is never blank — users new to the cockpit see what the
        tab is for. Each focused node becomes one row.
        """
        rows: list[dict] = []
        nodes = list(getattr(state, "nodes", ()) or ())
        scores = dict(getattr(state, "scores", {}) or {})
        intent = str(getattr(state, "intent", "") or "")
        is_divided = bool(getattr(state, "is_divided", False))
        if not nodes:
            rows = [
                {
                    "node": "-",
                    "score": "-",
                    "phase": "-",
                    "intent": t(self.lang, "focus_empty"),
                    "kind": "empty",
                }
            ]
        else:
            for i, node in enumerate(nodes):
                rows.append(
                    {
                        "node": node,
                        "score": f"{scores.get(node, 0.0):.2f}",
                        "phase": (t(self.lang, "focus_divided") if is_divided else "-"),
                        "intent": intent if i == 0 else "",
                        "kind": "focus",
                    }
                )
        self.focus_rows = rows
        if self.is_mounted:
            self._filtered_rows["focus"] = self._filter_rows(rows)
            self._reload_focus_table()
            if self.active == "focus":
                self._sync_active_table()

    def _reload_focus_table(self) -> None:
        if not self.is_mounted:
            return
        table = self.query_one(f"#{TABLE_IDS['focus']}", DataTable)
        table.clear()
        for row in self._filtered_rows.get("focus", []):
            kind = row.get("kind", "focus")
            key = f"focus:{row.get('node')}" if kind == "focus" else "focus:empty"
            table.add_row(
                str(row.get("node", "-")),
                str(row.get("score", "-")),
                str(row.get("phase", "-")),
                str(row.get("intent", "-")),
                key=key,
            )

    def _sync_active_table(self) -> None:
        active = self.active if self.active in TAB_ORDER else TAB_ORDER[0]
        self.active = active
        if not self.is_mounted:
            return
        for name in TAB_ORDER:
            table = self.query_one(f"#{TABLE_IDS[name]}", DataTable)
            if name == active:
                table.remove_class("hidden")
                table.add_class("tab-active")
            else:
                table.remove_class("tab-active")
                table.add_class("hidden")

    def _reload_risks_table(self) -> None:
        table = self.query_one(f"#{TABLE_IDS['risks']}", DataTable)
        table.clear(columns=False)
        rows = self._filtered_rows["risks"]
        if not rows:
            table.add_row("-", "-", "-", t(self.lang, "no_risks"), key="empty")
            table.move_cursor(row=0, column=0)
            return
        for index, row in enumerate(rows):
            table.add_row(
                self._risk_label("risk_" + str(row["severity"])),
                self._risk_label("risk_" + str(row["category"])),
                str(row["item"]),
                str(row["summary"]),
                key=f"risk-{index}",
            )
        table.move_cursor(row=0, column=0)

    def _reload_failure_table(self) -> None:
        table = self.query_one(f"#{TABLE_IDS['failures']}", DataTable)
        table.clear(columns=False)
        rows = self._filtered_rows["failures"]
        if not rows:
            table.add_row("-", t(self.lang, "no_failures"), "", "", key="empty")
            table.move_cursor(row=0, column=0)
            return
        for row in rows:
            table.add_row(
                str(row["failure_id"]),
                str(row["trigger"]),
                str(row["symptom"]),
                str(row["seen_count"]),
                key=str(row["failure_id"]),
            )
        table.move_cursor(row=0, column=0)

    def _reload_claims_table(self) -> None:
        table = self.query_one(f"#{TABLE_IDS['claims']}", DataTable)
        table.clear(columns=False)
        rows = self._filtered_rows["claims"]
        if not rows:
            table.add_row("-", "-", t(self.lang, "no_claims"), "-", "-", key="empty")
            table.move_cursor(row=0, column=0)
            return
        for row in rows:
            verified = t(self.lang, "yes") if row["verified"] else t(self.lang, "no")
            table.add_row(
                str(row["metric"]),
                str(row["value"]),
                str(row["dataset"]),
                verified,
                str(row["seeds"]),
                key=str(row["pin_id"]),
            )
        table.move_cursor(row=0, column=0)

    def _reload_literature_table(self) -> None:
        table = self.query_one(f"#{TABLE_IDS['literature']}", DataTable)
        table.clear(columns=False)
        rows = self._filtered_rows["literature"]
        if not rows:
            table.add_row("-", t(self.lang, "no_literature"), "-", "-", "-", key="empty")
            table.move_cursor(row=0, column=0)
            return
        for row in rows:
            # Bumped from 48→64 now that drill-in is the safety net for
            # elided text and most modern terminals run wide enough to
            # absorb the extra characters without crowding sibling columns.
            title = _truncate(str(row["title"]), 64)
            table.add_row(
                str(row["paper_id"]),
                title,
                str(row["year"] or "-"),
                str(row["task"]),
                f"{float(row['score']):.2f}",
                key=str(row["paper_id"]),
            )
        table.move_cursor(row=0, column=0)

    def _reload_reports_table(self) -> None:
        table = self.query_one(f"#{TABLE_IDS['reports']}", DataTable)
        table.clear(columns=False)
        rows = self._filtered_rows["reports"]
        if not rows:
            table.add_row("-", "-", "-", "-", t(self.lang, "reports_empty"), key="empty")
            table.move_cursor(row=0, column=0)
            return
        for row in rows:
            size = int(row.get("bytes") or 0)
            if size >= 1024 * 1024:
                size_label = f"{size / 1024 / 1024:.1f} MB"
            elif size >= 1024:
                size_label = f"{size / 1024:.1f} KB"
            else:
                size_label = f"{size} B"
            node_short = row.get("related_node_id") or "-"
            missing = bool(row.get("missing"))
            kind_cell = str(row.get("kind", "-"))
            if missing:
                kind_cell = f"{kind_cell} (missing)"
            table.add_row(
                kind_cell,
                str(node_short),
                str(row.get("format", "-")),
                size_label,
                str(row.get("generated_at", "-")),
                key=f"report-{row['report_id']}",
            )
        table.move_cursor(row=0, column=0)

    def _reload_corpus_table(self) -> None:
        table = self.query_one(f"#{TABLE_IDS['corpus']}", DataTable)
        table.clear(columns=False)
        rows = self._filtered_rows["corpus"]
        if not rows:
            table.add_row("-", "-", t(self.lang, "corpus_empty"), "", key="empty")
            table.move_cursor(row=0, column=0)
            return
        for row in rows:
            # Same logic as the literature table: drill-in carries the full
            # statement, the table just needs enough to scan the gist.
            statement = _truncate(str(row.get("statement", "")), 72)
            keywords = (
                f"L{row.get('n_lexical', 0)} / S{row.get('n_semantic', 0)}"
            )
            table.add_row(
                str(row["problem_id"]),
                str(row.get("primary_domain") or "-"),
                statement,
                keywords,
                key=str(row["problem_id"]),
            )
        table.move_cursor(row=0, column=0)

    def _reload_diagnostics_table(self) -> None:
        table = self.query_one(f"#{TABLE_IDS['diagnostics']}", DataTable)
        table.clear(columns=False)
        rows = self._filtered_rows["diagnostics"]
        if not rows:
            table.add_row(
                "-", "-", "-", "-", t(self.lang, "diagnostics_empty"), key="empty"
            )
            table.move_cursor(row=0, column=0)
            return
        for row in rows:
            status = str(row.get("status", "open"))
            icon = DIAGNOSTIC_STATUS_ICON.get(status, "?")
            # i18n returns the key itself as a fallback when missing; for
            # unknown statuses we fall back to the raw string instead so the
            # cell stays readable.
            status_label = t(self.lang, f"diagnostics_status_{status}")
            if status_label == f"diagnostics_status_{status}":
                status_label = status
            table.add_row(
                str(row["manifest_id"]),
                str(row.get("draft_id", "-")),
                f"{icon} {status_label}",
                str(row.get("snippet_count", 0)),
                str(row.get("flawed_count", 0)),
                key=f"manifest-{row['manifest_id']}",
            )
        table.move_cursor(row=0, column=0)

    def _reload_lean_table(self) -> None:
        table = self.query_one(f"#{TABLE_IDS['lean']}", DataTable)
        table.clear(columns=False)
        rows = self._filtered_rows["lean"]
        if not rows:
            table.add_row("-", "-", "-", "-", t(self.lang, "lean_empty"), key="empty")
            table.move_cursor(row=0, column=0)
            return
        for row in rows:
            status = str(row.get("status", "queued"))
            icon = LEAN_STATUS_ICON.get(status, "?")
            status_label = t(self.lang, f"lean_status_{status}")
            if status_label == f"lean_status_{status}":
                status_label = status
            duration = row.get("duration_sec")
            duration_text = (
                f"{float(duration):.1f}s"
                if isinstance(duration, (int, float))
                else "-"
            )
            triage = str(row.get("triage_difficulty") or "-")
            table.add_row(
                str(row["attempt_id"]),
                str(row.get("proposition_id", "-")),
                f"{icon} {status_label}",
                duration_text,
                triage,
                key=f"lean-{row['attempt_id']}",
            )
        table.move_cursor(row=0, column=0)

    def _filter_rows(self, rows: list[dict]) -> list[dict]:
        if not self._filter_text:
            return list(rows)
        return [
            row
            for row in rows
            if self._filter_text in " ".join(str(value) for value in row.values()).lower()
        ]

    def _refresh_title(self) -> None:
        active_id = self.active or "risks"
        # Proof-trunk + reports tabs use their own *_title keys; the
        # empirical four use the short single-word keys (risks /
        # failures / claims / literature).
        title_key = {
            "focus": "focus_title",
            "reports": "reports_title",
            "corpus": "corpus_title",
            "diagnostics": "diagnostics_title",
            "lean": "lean_title",
        }.get(active_id, active_id)
        active_label = t(self.lang, title_key)
        group_label = t(self.lang, f"tab_group_{group_of(active_id)}")
        suffix = (
            f" ({t(self.lang, 'filter_suffix', value=self._filter_text)})"
            if self._filter_text
            else ""
        )
        # "{group} · {tab}" — the middle dot is U+00B7, consistent with
        # other cockpit chrome (event-stream timestamps, HUD separators).
        composed = f"{group_label} · {active_label}"
        self.border_title = t(self.lang, "tabs_title", active=composed) + suffix

    def _refresh_group_bar(self) -> None:
        """Repaint the group strip above the table area.

        Each group renders as its localized label; the active group is
        wrapped in ``[active]…[/active]`` Rich markup so the theme can
        style it through the existing accent token. We deliberately do
        not show per-tab dots inside the chip — the border title
        already shows the active tab, and adding more density here
        would compete with the table content directly below.
        """
        if not self.is_mounted:
            return
        try:
            bar = self.query_one("#tabs-group-bar", Static)
        except Exception:
            return
        active_group = group_of(self.active or "risks")
        chips: list[str] = []
        for group_key, _names in TAB_GROUPS:
            label = t(self.lang, f"tab_group_{group_key}")
            if group_key == active_group:
                chips.append(f"[reverse]{label}[/reverse]")
            else:
                chips.append(f"[dim]{label}[/dim]")
        bar.update("  ".join(chips))

    def _risk_label(self, key: str) -> str:
        value = t(self.lang, key)
        return value if value != key else key.removeprefix("risk_")
