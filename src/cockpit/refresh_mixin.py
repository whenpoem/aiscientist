"""Pane data refresh methods for CockpitApp."""

from __future__ import annotations

from textual.css.query import NoMatches

from . import data
from .diagnostics import get_logger
from .refresh_coordinator import dispatch_events

_log = get_logger("refresh")


class CockpitRefreshMixin:
    def _refresh_graph(self) -> None:
        previous_node_id = self.selected_node_id or self.tree_pane.current_node_id()
        self.graph = data.fetch_graph()
        # Phase E3: push the bookmark set into the tree pane BEFORE
        # ``load_graph`` rebuilds the labels — that's the point where
        # ``_label_for`` reads ``self._bookmarks`` to decide whether to
        # prefix each row with ``✦``. Out-of-order would leave the
        # first paint without the indicator.
        self.tree_pane.set_bookmarks(self._settings.bookmarks)
        self.selected_node_id = self.tree_pane.load_graph(
            self.graph,
            show_refuted=self.show_refuted,
            filter_text=self._pane_filters["tree"],
            selected_node_id=previous_node_id,
        )

    def _refresh_tabs(self) -> None:
        failures = data.fetch_failures()
        claims = data.fetch_claims()
        graph = data.fetch_graph()
        heldout_budgets = data.fetch_heldout_budgets()
        self._set_tab_rows(
            risks=data.fetch_risks(
                claims=claims,
                failures=failures,
                graph=graph,
                heldout_budgets=heldout_budgets,
            ),
            failures=failures,
            claims=claims,
            literature=data.fetch_literature(),
            reports=data.fetch_reports(),
            corpus=data.fetch_corpus_problems(),
            diagnostics=data.fetch_diagnostic_manifests(),
            lean=data.fetch_lean_attempts(),
        )

    def _refresh_risks(self) -> None:
        self._set_tab_rows(risks=data.fetch_risks())

    def _refresh_failures(self) -> None:
        failures = data.fetch_failures()
        self._set_tab_rows(failures=failures, risks=data.fetch_risks(failures=failures))

    def _refresh_claims(self) -> None:
        claims = data.fetch_claims()
        self._set_tab_rows(claims=claims, risks=data.fetch_risks(claims=claims))

    def _refresh_literature(self) -> None:
        self._set_tab_rows(literature=data.fetch_literature())

    def _refresh_corpus(self) -> None:
        self._set_tab_rows(corpus=data.fetch_corpus_problems())

    def _refresh_diagnostics(self) -> None:
        self._set_tab_rows(diagnostics=data.fetch_diagnostic_manifests())

    def _refresh_lean(self) -> None:
        self._set_tab_rows(lean=data.fetch_lean_attempts())

    def _refresh_reports(self) -> None:
        self._set_tab_rows(reports=data.fetch_reports())

    def _set_tab_rows(
        self,
        *,
        risks: list[dict] | None = None,
        failures: list[dict] | None = None,
        claims: list[dict] | None = None,
        literature: list[dict] | None = None,
        corpus: list[dict] | None = None,
        diagnostics: list[dict] | None = None,
        lean: list[dict] | None = None,
        reports: list[dict] | None = None,
    ) -> None:
        self.tabs_pane.set_filter_text(self._pane_filters["tabs"])
        self.tabs_pane.set_rows(
            risks=risks if risks is not None else self.tabs_pane.risks_rows,
            failures=failures if failures is not None else self.tabs_pane.failures_rows,
            claims=claims if claims is not None else self.tabs_pane.claims_rows,
            literature=literature if literature is not None else self.tabs_pane.literature_rows,
            corpus=corpus if corpus is not None else self.tabs_pane.corpus_rows,
            diagnostics=(
                diagnostics if diagnostics is not None else self.tabs_pane.diagnostics_rows
            ),
            lean=lean if lean is not None else self.tabs_pane.lean_rows,
            reports=reports if reports is not None else self.tabs_pane.reports_rows,
        )

    def _refresh_counts(self) -> None:
        summary = data.fetch_dashboard()
        self.status_bar.set_summary(summary)
        # Tree border title shows live counts so users get scale info
        # without scanning the HUD. Filter mode takes precedence inside
        # tree_pane.set_counts (see its docstring).
        self.tree_pane.set_counts(
            {
                "active": int(summary.get("active_hypotheses", 0)),
                "refuted": int(summary.get("refuted_nodes", 0)),
            }
        )

    def _refresh_events(self) -> None:
        rows = data.fetch_new_events(self.last_event_id)
        if self.last_event_id <= 0:
            self.events_pane.set_rows(rows)
        elif rows:
            self.events_pane.append_rows(rows)
        self.last_event_id = int(rows[-1]["id"]) if rows else int(data.fetch_latest_event_id())
        self.events_pane.set_filter_text(self._pane_filters["events"])
        self.events_pane.set_relative_timestamps(self.relative_timestamps)
        # Phase E4: push the recent-events tail into the timeline strip
        # only when it is visible. The strip uses ``fetch_events`` (not
        # the delta cursor) because it always wants the most-recent
        # ``max_cells`` rows in chronological order — even if the user
        # just opened the strip after thousands of events have passed.
        try:
            timeline = self.timeline_pane
        except NoMatches:  # pragma: no cover - defensive
            timeline = None
        if timeline is not None and timeline.is_visible:
            try:
                timeline.set_events(data.fetch_new_events(0, limit=200))
            except Exception:  # pragma: no cover - defensive
                _log.exception("_refresh_events: timeline.set_events failed")

    def _dispatch_events(self, rows: list[dict]) -> None:
        dispatch_events(self, rows)

    def _apply_filter(self, target: str, value: str) -> None:
        self._pane_filters[target] = value
        if target == "tree":
            self.selected_node_id = self.tree_pane.load_graph(
                self.graph,
                show_refuted=self.show_refuted,
                filter_text=value,
                selected_node_id=self.selected_node_id,
            )
        elif target == "events":
            self.events_pane.set_filter_text(value)
        elif target == "activity":
            self.activity_pane.set_filter_text(value)
        else:
            self.tabs_pane.set_filter_text(value)


__all__ = ["CockpitRefreshMixin"]
