"""Refresh orchestration for Cockpit panes and derived surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .event_registry import refresh_targets_for

if TYPE_CHECKING:
    from .app import CockpitApp


def refresh_state(app: CockpitApp, *, include_events: bool) -> None:
    """Refresh a coherent full snapshot while preserving app-owned rendering."""
    app._refresh_graph()  # noqa: SLF001
    app._refresh_tabs()  # noqa: SLF001
    app._refresh_counts()  # noqa: SLF001
    if include_events:
        app._refresh_events()  # noqa: SLF001
    app._detail_override = False  # noqa: SLF001
    app.detail_pane.clear_override()
    app._refresh_detail()  # noqa: SLF001
    app._repaint_top_detail_screen()  # noqa: SLF001


def dispatch_events(app: CockpitApp, rows: list[dict]) -> None:
    """Route an event batch to the smallest affected pane refreshes."""
    kinds = {str(row.get("kind", "")) for row in rows}
    targets = refresh_targets_for(kinds)
    refreshers = {
        "graph": app._refresh_graph,  # noqa: SLF001
        "failures": app._refresh_failures,  # noqa: SLF001
        "claims": app._refresh_claims,  # noqa: SLF001
        "literature": app._refresh_literature,  # noqa: SLF001
        "risks": app._refresh_risks,  # noqa: SLF001
        "corpus": app._refresh_corpus,  # noqa: SLF001
        "diagnostics": app._refresh_diagnostics,  # noqa: SLF001
        "lean": app._refresh_lean,  # noqa: SLF001
        "reports": app._refresh_reports,  # noqa: SLF001
        "counts": app._refresh_counts,  # noqa: SLF001
        "detail": app._refresh_detail,  # noqa: SLF001
        "phase": app._refresh_phase,  # noqa: SLF001
        "activity": app._refresh_activity,  # noqa: SLF001
        "focus": app._refresh_focus,  # noqa: SLF001
    }
    for target, refresher in refreshers.items():
        if target in targets:
            refresher()


__all__ = ["dispatch_events", "refresh_state"]
