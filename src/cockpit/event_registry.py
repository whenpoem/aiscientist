"""Canonical Cockpit event vocabulary and refresh routing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EventSpec:
    family: str
    severity: str = "info"
    terminal_state: str | None = None
    singleton: bool = False
    time_bucket: bool = False
    refresh_targets: frozenset[str] = frozenset()


def _spec(
    family: str,
    *,
    severity: str = "info",
    terminal_state: str | None = None,
    singleton: bool = False,
    time_bucket: bool = False,
    refresh: tuple[str, ...] = (),
) -> EventSpec:
    return EventSpec(
        family=family,
        severity=severity,
        terminal_state=terminal_state,
        singleton=singleton,
        time_bucket=time_bucket,
        refresh_targets=frozenset(refresh),
    )


EVENT_REGISTRY: dict[str, EventSpec] = {
    # Graph and tournament.
    "graph_delta": _spec("graph", refresh=("graph",)),
    "branch_paused": _spec("graph", severity="high", terminal_state="failed"),
    "branch_pause_suggested": _spec("graph", severity="medium"),
    "branch_promoted": _spec("graph", terminal_state="done"),
    "auto_prune": _spec("graph"),
    "literature_ingested": _spec("graph", refresh=("literature",)),
    "bt_rating_updated": _spec("bt", severity="low"),
    "bt_fit_failed": _spec(
        "risk",
        severity="critical",
        terminal_state="blocked",
        singleton=True,
    ),
    "judgement_recorded": _spec("bt", refresh=("graph",)),
    # Verification and artifacts.
    "seed_run_recorded": _spec("verify", refresh=("claims",)),
    "prereg_locked": _spec("verify"),
    "prereg_resolved": _spec("verify", severity="medium", terminal_state="done"),
    "heldout_query_reserved": _spec("verify", refresh=("risks",)),
    "heldout_query_finished": _spec(
        "verify",
        severity="medium",
        terminal_state="done",
        refresh=("risks",),
    ),
    "claim_pinned": _spec("verify", refresh=("claims",)),
    "snapshot_created": _spec("verify", terminal_state="done"),
    "report_generated": _spec("verify", severity="low", refresh=("reports",)),
    "replay_branch_created": _spec("verify"),
    # Proof and Lean.
    "proof_corpus_ingested": _spec("prove", refresh=("corpus",)),
    "proof_corpus_reindex_progress": _spec(
        "prove",
        severity="low",
        time_bucket=True,
    ),
    "proof_segmented": _spec("prove", refresh=("diagnostics",)),
    "proof_diagnosis_recorded": _spec(
        "prove",
        severity="medium",
        refresh=("diagnostics",),
    ),
    "proof_diagnosis_complete": _spec(
        "prove",
        terminal_state="done",
        refresh=("diagnostics",),
    ),
    "proof_correction_applied": _spec(
        "prove",
        terminal_state="done",
        refresh=("diagnostics",),
    ),
    "lean_proof_succeeded": _spec(
        "lean",
        terminal_state="done",
        refresh=("lean",),
    ),
    "lean_proof_failed": _spec(
        "lean",
        severity="high",
        terminal_state="failed",
        refresh=("lean",),
    ),
    "lean_proof_recorded": _spec("lean", refresh=("lean",)),
    # User and agent activity.
    "intervention": _spec("intervention", severity="medium"),
    "intervention_undone": _spec("intervention", severity="medium"),
    "agent_narration": _spec("narrate", severity="low", singleton=True),
    "note": _spec("narrate", severity="low", singleton=True),
    "phase_set": _spec("narrate", severity="low", singleton=True),
    # Risks.
    "budget_exceeded": _spec(
        "risk",
        severity="critical",
        terminal_state="blocked",
        singleton=True,
    ),
    "prov_dag_stale": _spec(
        "risk",
        severity="critical",
        terminal_state="blocked",
        singleton=True,
    ),
    "failure_added": _spec(
        "risk",
        severity="high",
        singleton=True,
        refresh=("failures",),
    ),
}

FAMILIES: tuple[str, ...] = (
    "graph",
    "bt",
    "verify",
    "prove",
    "lean",
    "intervention",
    "narrate",
    "risk",
)
COMMON_REFRESH_TARGETS = frozenset({"counts", "detail", "phase", "activity", "focus"})


def refresh_targets_for(kinds: set[str]) -> frozenset[str]:
    targets = set(COMMON_REFRESH_TARGETS)
    for kind in kinds:
        spec = EVENT_REGISTRY.get(kind)
        if spec is not None:
            targets.update(spec.refresh_targets)
    return frozenset(targets)


__all__ = [
    "COMMON_REFRESH_TARGETS",
    "EVENT_REGISTRY",
    "EventSpec",
    "FAMILIES",
    "refresh_targets_for",
]
