"""Refresh orchestration for Cockpit panes and derived surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    if {"graph_delta", "judgement_recorded"} & kinds:
        app._refresh_graph()  # noqa: SLF001
    if "failure_added" in kinds:
        app._refresh_failures()  # noqa: SLF001
    if {"claim_pinned", "seed_run_recorded"} & kinds:
        app._refresh_claims()  # noqa: SLF001
    if "literature_ingested" in kinds:
        app._refresh_literature()  # noqa: SLF001
    if {"heldout_query_reserved", "heldout_query_finished"} & kinds:
        app._refresh_risks()  # noqa: SLF001
    if "proof_corpus_ingested" in kinds:
        app._refresh_corpus()  # noqa: SLF001
    if {
        "proof_segmented",
        "proof_diagnosis_recorded",
        "proof_diagnosis_complete",
        "proof_correction_applied",
    } & kinds:
        app._refresh_diagnostics()  # noqa: SLF001
    if {"lean_proof_succeeded", "lean_proof_failed", "lean_proof_recorded"} & kinds:
        app._refresh_lean()  # noqa: SLF001
    if "report_generated" in kinds:
        app._refresh_reports()  # noqa: SLF001
    app._refresh_counts()  # noqa: SLF001
    app._refresh_detail()  # noqa: SLF001
    app._refresh_phase()  # noqa: SLF001
    app._refresh_activity()  # noqa: SLF001
    app._refresh_focus()  # noqa: SLF001


__all__ = ["dispatch_events", "refresh_state"]
