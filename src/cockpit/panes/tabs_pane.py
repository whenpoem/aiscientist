"""Right-side tabbed tables for the cockpit TUI."""

from __future__ import annotations

from textual.widgets import DataTable, TabbedContent, TabPane

from cockpit.i18n import t

TAB_ORDER = ("risks", "failures", "claims", "literature")
TABLE_IDS = {
    "risks": "risks-table",
    "failures": "failures-table",
    "claims": "claims-table",
    "literature": "literature-table",
}


class RightTabsPane(TabbedContent):
    """Failures, claims, and literature tables."""

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
    ) -> None:
        self.risks_rows = list(risks)
        self.failures_rows = list(failures)
        self.claims_rows = list(claims)
        self.literature_rows = list(literature)
        self._reload_tables()

    def cycle_tab(self) -> None:
        current = self.active or TAB_ORDER[0]
        index = TAB_ORDER.index(current)
        self.active = TAB_ORDER[(index + 1) % len(TAB_ORDER)]
        self._refresh_title()
        self.current_table().focus()

    def move_cursor_by(self, delta: int) -> None:
        rows = self._filtered_rows[self.active or "risks"]
        if not rows:
            return
        table = self.current_table()
        current = table.cursor_row or 0
        target = max(0, min(len(rows) - 1, current + delta))
        table.move_cursor(row=target, column=0)

    def move_cursor_to_top(self) -> None:
        if self._filtered_rows[self.active or "risks"]:
            self.current_table().move_cursor(row=0, column=0)

    def move_cursor_to_bottom(self) -> None:
        rows = self._filtered_rows[self.active or "risks"]
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
        }
        self._filtered_rows = {
            name: self._filter_rows(rows) for name, rows in payloads.items()
        }
        self._reload_risks_table()
        self._reload_failure_table()
        self._reload_claims_table()
        self._reload_literature_table()
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

    def _filter_rows(self, rows: list[dict]) -> list[dict]:
        if not self._filter_text:
            return list(rows)
        return [
            row
            for row in rows
            if self._filter_text in " ".join(str(value) for value in row.values()).lower()
        ]

    def _refresh_title(self) -> None:
        active = t(self.lang, self.active or "risks")
        suffix = (
            f" ({t(self.lang, 'filter_suffix', value=self._filter_text)})"
            if self._filter_text
            else ""
        )
        self.border_title = t(self.lang, "tabs_title", active=active) + suffix

    def _risk_label(self, key: str) -> str:
        value = t(self.lang, key)
        return value if value != key else key.removeprefix("risk_")
