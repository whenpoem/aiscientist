"""Right-side tabbed tables for the cockpit TUI.

Tabs (in cycle order):

1. ``risks``        — composite risk view (claims + seeds + failures + budgets)
2. ``failures``     — cross-domain failure ledger (mem_failures)
3. ``claims``       — pinned metrics (ver_metric_pins + seed verdicts)
4. ``literature``   — ingested papers (mem_lit_compressed)
5. ``corpus``       — proof corpus (prv_corpus_problems)            -- v4.1.0a0
6. ``diagnostics``  — diagnostic manifests (prv_diagnostic_manifests) -- v4.1.0a0
7. ``lean``         — Lean attempts (prv_lean_attempts)             -- v4.1.0a0

The three proof-trunk tabs render empty-state hints when their tables are
absent (v3.x DB) or empty (fresh install pre-seed-corpus). All cells go
through ``cockpit.i18n.t`` so the bilingual contract holds.
"""

from __future__ import annotations

from textual.widgets import DataTable, TabbedContent, TabPane

from cockpit.i18n import t

TAB_ORDER = (
    "risks",
    "failures",
    "claims",
    "literature",
    "corpus",
    "diagnostics",
    "lean",
)
TABLE_IDS = {
    "risks": "risks-table",
    "failures": "failures-table",
    "claims": "claims-table",
    "literature": "literature-table",
    "corpus": "corpus-table",
    "diagnostics": "diagnostics-table",
    "lean": "lean-table",
}

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


class RightTabsPane(TabbedContent):
    """Risks, failures, claims, literature, and proof-trunk tables."""

    def __init__(self) -> None:
        super().__init__(initial="risks")
        self.id = "tabs-pane"
        self.classes = "pane"
        self.lang = "en"
        self.border_title = t(self.lang, "tabs_title_all")
        self.risks_rows: list[dict] = []
        self.failures_rows: list[dict] = []
        self.claims_rows: list[dict] = []
        self.literature_rows: list[dict] = []
        self.corpus_rows: list[dict] = []
        self.diagnostics_rows: list[dict] = []
        self.lean_rows: list[dict] = []
        self._filtered_rows: dict[str, list[dict]] = {key: [] for key in TAB_ORDER}
        self._filter_text = ""

    def compose(self):
        with TabPane(t(self.lang, "risks"), id="risks"):
            yield DataTable(id=TABLE_IDS["risks"], cursor_type="row")
        with TabPane(t(self.lang, "failures"), id="failures"):
            yield DataTable(id=TABLE_IDS["failures"], cursor_type="row")
        with TabPane(t(self.lang, "claims"), id="claims"):
            yield DataTable(id=TABLE_IDS["claims"], cursor_type="row")
        with TabPane(t(self.lang, "literature"), id="literature"):
            yield DataTable(id=TABLE_IDS["literature"], cursor_type="row")
        with TabPane(t(self.lang, "corpus_title"), id="corpus"):
            yield DataTable(id=TABLE_IDS["corpus"], cursor_type="row")
        with TabPane(t(self.lang, "diagnostics_title"), id="diagnostics"):
            yield DataTable(id=TABLE_IDS["diagnostics"], cursor_type="row")
        with TabPane(t(self.lang, "lean_title"), id="lean"):
            yield DataTable(id=TABLE_IDS["lean"], cursor_type="row")

    def on_mount(self) -> None:
        self._configure_tables()
        self._refresh_title()

    def set_language(self, lang: str) -> None:
        self.lang = lang
        if self.is_mounted:
            self._configure_tables()
            self._reload_tables()
        self._refresh_title()

    def _configure_tables(self) -> None:
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
    ) -> None:
        self.risks_rows = list(risks)
        self.failures_rows = list(failures)
        self.claims_rows = list(claims)
        self.literature_rows = list(literature)
        # Proof-trunk rows are optional in the public set_rows signature so
        # callers that only know about the empirical four don't have to
        # change. New code (App._refresh_tabs) always passes all seven.
        self.corpus_rows = list(corpus or [])
        self.diagnostics_rows = list(diagnostics or [])
        self.lean_rows = list(lean or [])
        self._reload_tables()

    def cycle_tab(self) -> None:
        current = self.active or TAB_ORDER[0]
        index = TAB_ORDER.index(current) if current in TAB_ORDER else 0
        self.active = TAB_ORDER[(index + 1) % len(TAB_ORDER)]
        self._refresh_title()
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

    def watch_active(self, _old: str | None, _new: str | None) -> None:
        self._refresh_title()

    def _reload_tables(self) -> None:
        payloads = {
            "risks": self.risks_rows,
            "failures": self.failures_rows,
            "claims": self.claims_rows,
            "literature": self.literature_rows,
            "corpus": self.corpus_rows,
            "diagnostics": self.diagnostics_rows,
            "lean": self.lean_rows,
        }
        self._filtered_rows = {
            name: self._filter_rows(rows) for name, rows in payloads.items()
        }
        self._reload_risks_table()
        self._reload_failure_table()
        self._reload_claims_table()
        self._reload_literature_table()
        self._reload_corpus_table()
        self._reload_diagnostics_table()
        self._reload_lean_table()
        self._refresh_title()

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
            title = str(row["title"])
            if len(title) > 48:
                title = title[:45] + "..."
            table.add_row(
                str(row["paper_id"]),
                title,
                str(row["year"] or "-"),
                str(row["task"]),
                f"{float(row['score']):.2f}",
                key=str(row["paper_id"]),
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
            statement = str(row.get("statement", ""))
            if len(statement) > 56:
                statement = statement[:53] + "..."
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
        # Proof-trunk tabs use their own *_title keys; empirical tabs use the
        # short single-word keys (risks/failures/claims/literature).
        title_key = {
            "corpus": "corpus_title",
            "diagnostics": "diagnostics_title",
            "lean": "lean_title",
        }.get(active_id, active_id)
        active_label = t(self.lang, title_key)
        suffix = (
            f" ({t(self.lang, 'filter_suffix', value=self._filter_text)})"
            if self._filter_text
            else ""
        )
        self.border_title = t(self.lang, "tabs_title", active=active_label) + suffix

    def _risk_label(self, key: str) -> str:
        value = t(self.lang, key)
        return value if value != key else key.removeprefix("risk_")
