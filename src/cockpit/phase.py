"""Phase derivation for the cockpit's top status strip.

Pure-function module that maps the recent ``cockpit_events`` tail to a
single high-level "what is the agent doing right now" phase. The
derivation is deterministic given a list of events plus a ``now``
timestamp; the ``*_from_db`` wrapper exists so the TUI can call this
without owning the SQLite plumbing.

This module owns NO state — phase is recomputed each tick (per ADR
0007 "workflow state inferred from data, not stored in a state
machine"). The eight named phases below cover the SOP-defined research
loop:

    idle        — no recent activity (silence > idle_threshold_sec)
    explore     — graph / literature discovery
    select      — BT tournament / judgement
    experiment  — runs, failures, redirects
    verify      — preregistration / heldout / seed / budget / DAG checks
    prove       — proof segment / diagnose / correct / Lean attempts
    review      — claim pin / snapshot / report / replay branch
    narrate     — agent_narration without other phase signal

Precedence: an explicit ``phase_set`` event (emitted by
``cockpit__set_phase``) overrides derivation; otherwise the kind-family
table below decides. A 90-second silence resets to ``idle``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from cockpit import data

PHASES: tuple[str, ...] = (
    "idle",
    "explore",
    "select",
    "experiment",
    "verify",
    "prove",
    "review",
    "narrate",
)

# Maps every emitted kind to a phase. Kinds not in this table fall to
# ``None`` (no contribution). Multi-line groups mirror the trunk that
# emits them so adding new kinds stays auditable.
KIND_PHASE: dict[str, str] = {
    # prove trunk
    "proof_corpus_ingested": "prove",
    "proof_corpus_reindex_progress": "prove",
    "proof_segmented": "prove",
    "proof_diagnosis_recorded": "prove",
    "proof_diagnosis_complete": "prove",
    "proof_correction_applied": "prove",
    "lean_proof_succeeded": "prove",
    "lean_proof_failed": "prove",
    "lean_proof_recorded": "prove",
    # verify trunk
    "seed_run_recorded": "verify",
    "prereg_locked": "verify",
    "prereg_resolved": "verify",
    "heldout_query_reserved": "verify",
    "heldout_query_finished": "verify",
    "budget_exceeded": "verify",
    "prov_dag_stale": "verify",
    # review / artifacts
    "claim_pinned": "review",
    "snapshot_created": "review",
    "report_generated": "review",
    "replay_branch_created": "review",
    # experiment-side
    "failure_added": "experiment",
    # select / tournament
    "judgement_recorded": "select",
    "bt_rating_updated": "select",
    "branch_pause_suggested": "select",
    "branch_paused": "select",
    "branch_promoted": "select",
    "auto_prune": "select",
    # explore
    "graph_delta": "explore",
    "literature_ingested": "explore",
    # narrate (lowest)
    "agent_narration": "narrate",
    "note": "narrate",
}

# Phase strip colour token per phase (resolved by widget via
# theme.color() / style()). Values reference semantic tokens so
# light/dark themes adapt automatically.
PHASE_COLOR_TOKEN: dict[str, str] = {
    "idle": "foreground-subtle",
    "explore": "kind-question",
    "select": "kind-hypothesis",
    "experiment": "kind-experiment",
    "verify": "kind-evidence",
    "prove": "kind-proposition",
    "review": "warning",
    "narrate": "foreground-muted",
}

# Glyph for the phase badge. Plain ASCII / basic Unicode so cmd.exe,
# Windows Terminal, iTerm, alacritty all render consistently — no
# emoji.
PHASE_GLYPH: dict[str, str] = {
    "idle": " ",
    "explore": "◇",
    "select": "⚖",
    "experiment": "▶",
    "verify": "✓",
    "prove": "⊢",
    "review": "★",
    "narrate": "\"",
}


@dataclass(slots=True, frozen=True)
class Phase:
    """Result of one phase derivation pass.

    ``confidence`` is the share of recent events that matched the
    winning phase, in [0.0, 1.0]. ``since`` is the ISO timestamp of the
    first event in the window that supports the current phase, useful
    for "BT tournament · 3m" style relative-time rendering.
    ``source_kinds`` records which kinds drove the classification,
    capped to the 5 most recent for display.
    """

    name: str
    confidence: float = 0.0
    since: str = ""
    last_event_id: int = 0
    source_kinds: tuple[str, ...] = field(default_factory=tuple)
    intent: str = ""
    focus_nodes: tuple[str, ...] = field(default_factory=tuple)


_IDLE = Phase(name="idle", confidence=0.0)


def _parse_timestamp(raw: str) -> datetime | None:
    """Parse cockpit_events.created_at into an aware datetime.

    Accepts both ISO-8601 (``now_utc_iso``) and SQLite default
    ``'%Y-%m-%d %H:%M:%S'`` strings. Naive results are assumed UTC,
    matching the rest of the cockpit codebase (events_pane.py uses
    the same shape).
    """
    if not raw:
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _phase_for_event(event: dict) -> str | None:
    """Return the phase contributed by one event, or None."""
    kind = str(event.get("kind", ""))
    if kind == "phase_set":
        # Explicit override — caller handles before falling into the
        # majority vote.
        payload = event.get("payload") or {}
        explicit = str(payload.get("phase", "")).strip()
        return explicit if explicit in PHASES else None
    return KIND_PHASE.get(kind)


def derive_phase(
    events: list[dict],
    *,
    now: datetime | None = None,
    idle_threshold_sec: int = 90,
    window_size: int = 50,
) -> Phase:
    """Derive the current phase from a list of cockpit_events rows.

    Events should be ordered oldest→newest (matches
    ``data.fetch_new_events`` output). ``now`` defaults to current UTC.
    Window: at most ``window_size`` most-recent events participate; the
    older tail is ignored so phase reacts to recent activity.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not events:
        return _IDLE

    recent = events[-window_size:] if len(events) > window_size else list(events)

    # Idle check uses the newest event's age.
    newest = recent[-1]
    newest_ts = _parse_timestamp(str(newest.get("created_at", "")))
    if newest_ts is not None:
        age = (now - newest_ts).total_seconds()
        if age > idle_threshold_sec:
            return Phase(
                name="idle",
                confidence=0.0,
                since=str(newest.get("created_at", "")),
                last_event_id=int(newest.get("id", 0) or 0),
                source_kinds=(),
            )

    # Explicit phase_set wins — find the most recent one in window.
    latest_set: dict | None = None
    for ev in reversed(recent):
        if str(ev.get("kind", "")) == "phase_set":
            payload = ev.get("payload") or {}
            explicit = str(payload.get("phase", "")).strip()
            if explicit in PHASES:
                latest_set = ev
                break

    # Tally phase contributions across the window.
    tally: dict[str, int] = {}
    last_for_phase: dict[str, dict] = {}
    first_for_phase: dict[str, dict] = {}
    for ev in recent:
        contribution = _phase_for_event(ev)
        if contribution is None:
            continue
        tally[contribution] = tally.get(contribution, 0) + 1
        last_for_phase[contribution] = ev
        first_for_phase.setdefault(contribution, ev)

    if latest_set is not None:
        explicit_payload = latest_set.get("payload") or {}
        explicit_name = str(explicit_payload.get("phase", "")).strip()
        focus_nodes = explicit_payload.get("focus_nodes") or []
        if not isinstance(focus_nodes, list):
            focus_nodes = []
        intent = str(explicit_payload.get("intent", ""))[:200]
        # Confidence for an explicit set: how many recent events agree.
        agree = tally.get(explicit_name, 0)
        total = sum(tally.values()) or 1
        return Phase(
            name=explicit_name,
            confidence=min(1.0, max(0.05, agree / total)) if agree else 0.5,
            since=str(latest_set.get("created_at", "")),
            last_event_id=int(latest_set.get("id", 0) or 0),
            source_kinds=_source_kinds(recent, explicit_name),
            intent=intent,
            focus_nodes=tuple(str(n) for n in focus_nodes[:8]),
        )

    if not tally:
        return Phase(
            name="idle",
            confidence=0.0,
            since=str(newest.get("created_at", "")),
            last_event_id=int(newest.get("id", 0) or 0),
            source_kinds=(),
        )

    # Pick the phase with the most contributions; tie-break by the
    # phase whose most-recent contribution is newer (preferring the
    # latest activity).
    def _last_id(name: str) -> int:
        ev = last_for_phase.get(name)
        return int(ev.get("id", 0) or 0) if ev else 0

    ranked = sorted(
        tally.items(),
        key=lambda item: (item[1], _last_id(item[0])),
        reverse=True,
    )
    winner_name, winner_count = ranked[0]

    # Switch-out-of-idle anti-flicker: require >=2 supporting events
    # before claiming a non-idle phase. (Single-event spikes look
    # like idle.) Once a non-idle phase has >=2 events it can pivot
    # to another non-idle phase on a single newer event because the
    # tie-break above already prefers recency.
    if winner_count < 2:
        return Phase(
            name="idle",
            confidence=0.0,
            since=str(newest.get("created_at", "")),
            last_event_id=int(newest.get("id", 0) or 0),
            source_kinds=(),
        )

    total = sum(tally.values())
    confidence = winner_count / total if total else 0.0
    first_ev = first_for_phase[winner_name]
    last_ev = last_for_phase[winner_name]
    return Phase(
        name=winner_name,
        confidence=confidence,
        since=str(first_ev.get("created_at", "")),
        last_event_id=int(last_ev.get("id", 0) or 0),
        source_kinds=_source_kinds(recent, winner_name),
    )


def _source_kinds(events: list[dict], phase_name: str) -> tuple[str, ...]:
    """Return the last 5 distinct kinds that contributed to ``phase_name``."""
    seen: list[str] = []
    for ev in reversed(events):
        if _phase_for_event(ev) == phase_name:
            kind = str(ev.get("kind", ""))
            if kind and kind not in seen:
                seen.append(kind)
                if len(seen) >= 5:
                    break
    return tuple(reversed(seen))


def derive_phase_from_db(
    *,
    lookback: int = 200,
    now: datetime | None = None,
    idle_threshold_sec: int = 90,
) -> Phase:
    """Convenience wrapper: read recent events from SQLite and derive.

    Returns the same ``Phase`` shape as :func:`derive_phase`. Uses
    ``data.fetch_new_events(last_event_id=0, limit=lookback)`` which
    returns the newest ``lookback`` rows sorted oldest→newest — the
    exact contract :func:`derive_phase` expects.
    """
    events = data.fetch_new_events(last_event_id=0, limit=max(1, lookback))
    return derive_phase(events, now=now, idle_threshold_sec=idle_threshold_sec)
