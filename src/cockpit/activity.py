"""Activity card aggregation for the cockpit's primary visual surface.

Pure-function module that groups a stream of ``cockpit_events`` rows
into :class:`ActivityCard` objects. The cards model "research actions"
the way a researcher would describe them — "BT tournament for
hyp_03/05/06", "Proof draft for prop_12" — rather than the raw
verbs the MCP servers emit.

ADR alignment (0007 — workflow state inferred from data, not stored):
``aggregate(events)`` is deterministic over its input list and owns
no state. The UI re-runs it every tick. No new tables.

Card identity
-------------
Each card has a deterministic ``card_id`` derived from
``(family, focus_or_bucket)``. Same key = same card across ticks, so
the UI can apply diffs (new event lines, status change) without
reordering.

Grouping rules (priority order)
-------------------------------
1. ``(family, focus_node_id)`` — when the event payload carries a
   node target (``node_id`` / ``proposition_id`` / ``target`` /
   ``winner_node_id``). One card per research object per family.
2. ``(family, time_bucket_60s)`` — for high-volume events without a
   node target (currently ``proof_corpus_reindex_progress``). Avoids
   one-card-per-progress-tick spam.
3. Singleton — one card per event for genuinely independent signals
   (``budget_exceeded``, ``prov_dag_stale``, ``failure_added``,
   ``agent_narration``, ``phase_set``).

Lifecycle
---------
A card is ``running`` while it sees fresh events. Terminal kinds
(see ``TERMINAL_KINDS``) move it to ``done``; failure kinds to
``failed``; budget/DAG breach correlated to the focus to
``blocked``. After 120 s in a terminal state the card is considered
"closed" — still in the list (history), but the activity pane may
choose to dim it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cockpit import data
from cockpit.event_registry import EVENT_REGISTRY, FAMILIES

# Event family, severity, terminal-state, grouping, and refresh semantics all
# derive from one registry so a newly emitted kind cannot silently diverge
# between Activity rendering and pane refresh routing.
KIND_FAMILY: dict[str, str] = {
    kind: spec.family for kind, spec in EVENT_REGISTRY.items()
}

# Glyph for the card's family chip. Plain Unicode — no emoji.
#
# Phase B (visual axis disambiguation): ``graph`` moves off ◇ to free
# that glyph for ``kind=question`` (and the phase axis no longer claims
# it either). ``risk`` moves off ▲ to free that glyph for
# ``kind=hypothesis`` and to remove the severity-high/risk-family
# "▲ ▲ branch_paused" double-triangle the user called out. The
# verify/prove/narrate overlaps with the phase axis are deliberate —
# see :data:`cockpit.phase.PHASE_GLYPH`.
FAMILY_GLYPH: dict[str, str] = {
    "graph": "⊞",       # was ◇ (collided with kind=question)
    "bt": "⚖",
    "verify": "✓",
    "prove": "⊢",
    "lean": "λ",
    "intervention": "!",
    "narrate": "❝",     # was " — matches phase=narrate, better typography
    "risk": "⚠",        # was ▲ (collided with kind=hypothesis + severity=high)
}

# Color token (resolved via cockpit.theme.color()) per family.
FAMILY_COLOR_TOKEN: dict[str, str] = {
    "graph": "kind-question",
    "bt": "kind-hypothesis",
    "verify": "kind-evidence",
    "prove": "kind-proposition",
    "lean": "kind-proposition",
    "intervention": "warning",
    "narrate": "foreground-muted",
    "risk": "error",
}

# Severity bands. Cards roll up to the MAX of their constituents.
SEVERITY_ORDER: tuple[str, ...] = (
    "info",
    "low",
    "medium",
    "high",
    "critical",
)

KIND_SEVERITY: dict[str, str] = {
    kind: spec.severity for kind, spec in EVENT_REGISTRY.items()
}

# Glyph + style for severity. Pairs with color via cockpit.theme.color().
#
# Phase B (visual axis disambiguation): severity now uses a density
# gradient (block shading) instead of mixed shape glyphs. The visual
# language reads as "intensity" without overlapping kind (geometric
# shapes), family (mixed symbols), or phase (process-flow). The
# critical / high / medium / low / info ramp matches how the eye
# parses ink density — heaviest ink = loudest signal.
SEVERITY_GLYPH: dict[str, str] = {
    "critical": "█",   # was ■ (collided with kind=proposition)
    "high": "▓",       # was ▲ (collided with kind=hypothesis + family=risk)
    "medium": "▒",     # was ● (clashed visually with HUD heartbeat dot)
    "low": "░",        # was · (now part of a coherent density ramp)
    "info": " ",
}

SEVERITY_COLOR_TOKEN: dict[str, str] = {
    "critical": "severity-critical",
    "high": "severity-high",
    "medium": "severity-medium",
    "low": "severity-low",
    "info": "severity-info",
}

# Terminal kinds — push card → done. Failure / blocker kinds handled
# below in _terminal_state.
TERMINAL_KINDS: frozenset[str] = frozenset(
    kind for kind, spec in EVENT_REGISTRY.items() if spec.terminal_state == "done"
)
FAILURE_KINDS: frozenset[str] = frozenset(
    kind for kind, spec in EVENT_REGISTRY.items() if spec.terminal_state == "failed"
)
BLOCKED_KINDS: frozenset[str] = frozenset(
    kind for kind, spec in EVENT_REGISTRY.items() if spec.terminal_state == "blocked"
)

# Card status order for display sort (running first, then issues, then done).
STATUS_ORDER: dict[str, int] = {
    "running": 0,
    "blocked": 1,
    "failed": 2,
    "done": 3,
}

# Kinds that should always be a singleton card.
SINGLETON_KINDS: frozenset[str] = frozenset(
    kind for kind, spec in EVENT_REGISTRY.items() if spec.singleton
)

# Time bucket fallback for events without a node target.
TIME_BUCKET_KINDS: frozenset[str] = frozenset(
    kind for kind, spec in EVENT_REGISTRY.items() if spec.time_bucket
)

# How long a terminal card stays in the active list before being
# considered "closed". The activity pane may dim closed cards or move
# them to a "recent" subsection.
CLOSE_GRACE_SECONDS = 120

# Default visible window: events newer than this many seconds drive
# the active card list.
DEFAULT_WINDOW_SECONDS = 1800  # 30 min

# Hard cap on card body lines so a busy card doesn't push others off
# screen.
CARD_BODY_LINES_MAX = 6


@dataclass(slots=True, frozen=True)
class ActivityCard:
    """One research action as a card.

    See module docstring for invariants. Frozen so consumers can hash
    by identity / equality without paranoia about mutation between
    ticks.
    """

    card_id: str
    family: str
    title: str
    focus_node_id: str | None
    status: str
    severity: str
    first_event_id: int
    last_event_id: int
    first_at: str
    last_at: str
    event_count: int
    summary_fields: dict = field(default_factory=dict)
    recent_event_lines: tuple[str, ...] = field(default_factory=tuple)
    closed_at: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload_node_id(payload: dict) -> str | None:
    """Resolve the most-likely focus node id from a payload.

    Different MCP servers carry the target id under different keys.
    Order matters: ``winner_node_id`` is more specific than
    ``node_id`` (the latter is sometimes the loser). For interventions
    the ``target`` field carries the node ref.
    """
    for key in (
        "winner_node_id",
        "proposition_id",
        "draft_id",
        "node_id",
        "target",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _kind_severity(kind: str, payload: dict) -> str:
    """Severity for one event. Payload-aware on a few kinds."""
    base = KIND_SEVERITY.get(kind, "info")
    if kind == "intervention" and str(payload.get("kind") or "") == "halt":
        return "high"
    if kind == "proof_diagnosis_recorded" and not payload.get("is_flawed"):
        return "low"
    if kind == "heldout_query_finished" and str(payload.get("status") or "") == "failed":
        return "high"
    if kind == "prereg_resolved":
        verdict = str(payload.get("verdict") or payload.get("status") or "")
        if verdict in {"missed", "unmet", "failed"}:
            return "high"
    return base


def _severity_max(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.index(a) >= SEVERITY_ORDER.index(b) else b


def _bucket_minute(iso_ts: str) -> str:
    """Return a 60-s bucket label for grouping reindex-style chatter."""
    if not iso_ts:
        return "no_ts"
    candidate = iso_ts.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(iso_ts, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return iso_ts[:16]
    return parsed.strftime("%Y-%m-%dT%H:%M")


def _grouping_key(event: dict) -> tuple[str, str] | None:
    """Compute the (family, group_key) tuple for one event.

    Returns ``("singleton:<id>", "")`` for singleton kinds so they
    cannot merge with anything else.
    """
    kind = str(event.get("kind", ""))
    family = KIND_FAMILY.get(kind)
    if family is None:
        return None
    if kind in SINGLETON_KINDS:
        # Make each singleton uniquely keyed by event id.
        return (family, f"singleton:{event.get('id', 0)}")
    payload = event.get("payload") or {}
    node_id = _payload_node_id(payload)
    if node_id:
        return (family, f"node:{node_id}")
    if kind in TIME_BUCKET_KINDS:
        return (family, f"bucket:{_bucket_minute(str(event.get('created_at', '')))}")
    # Fallback: bucket by minute so high-volume kindless events still
    # group sensibly.
    return (family, f"bucket:{_bucket_minute(str(event.get('created_at', '')))}")


def _card_id(family: str, group_key: str) -> str:
    """Deterministic short id for a card. Same input ⇒ same output."""
    h = hashlib.blake2b(f"{family}::{group_key}".encode(), digest_size=6)
    return h.hexdigest()


def _terminal_state(event_kind: str) -> str | None:
    if event_kind in TERMINAL_KINDS:
        return "done"
    if event_kind in FAILURE_KINDS:
        return "failed"
    if event_kind in BLOCKED_KINDS:
        return "blocked"
    return None


def _title_for(family: str, focus: str | None, sample_kind: str) -> str:
    """Short human-readable title for a card. The activity pane
    decorates this with severity + status glyphs; the title itself is
    just the noun phrase.
    """
    if focus:
        return f"{family} · {focus}"
    return f"{family} · {sample_kind}"


def _line_for(event: dict) -> str:
    """One short event-line summary suitable for a card body row."""
    kind = str(event.get("kind", ""))
    payload = event.get("payload") or {}
    ts = str(event.get("created_at", ""))[11:19]  # HH:MM:SS slice if present
    if kind == "graph_delta":
        return f"{ts}  + {payload.get('kind', '-')} {payload.get('node_id', '-')}"
    if kind == "judgement_recorded":
        return (
            f"{ts}  {payload.get('winner_node_id', '-')} won vs "
            f"{payload.get('a_node_id', '-')}/{payload.get('b_node_id', '-')}"
        )
    if kind == "bt_rating_updated":
        return f"{ts}  bt · {payload.get('node_id', '-')}"
    if kind == "proof_diagnosis_recorded":
        flag = "FLAW" if payload.get("is_flawed") else "ok"
        return f"{ts}  snippet {payload.get('snippet_id', '-')} {flag}"
    if kind in {"lean_proof_recorded", "lean_proof_succeeded", "lean_proof_failed"}:
        dur = payload.get("duration_sec")
        dur_s = f" {dur:.1f}s" if isinstance(dur, (int, float)) else ""
        return f"{ts}  {kind[5:]} · prop={payload.get('proposition_id', '-')}{dur_s}"
    if kind == "intervention":
        return f"{ts}  {payload.get('kind', '-')} → {payload.get('target', '-')}"
    if kind == "agent_narration":
        text = str(payload.get("text", ""))
        if len(text) > 80:
            text = text[:77] + "…"
        return f"{ts}  \" {text}"
    if kind == "phase_set":
        return f"{ts}  phase → {payload.get('phase', '-')}"
    # Default: just the kind name.
    return f"{ts}  {kind}"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(
    events: list[dict],
    *,
    now: datetime | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> list[ActivityCard]:
    """Group ``events`` into ActivityCards.

    Determinism contract: same input list + same ``now`` ⇒ identical
    output (including ``card_id`` and ordering). The activity pane
    leans on this to diff between ticks without re-laying-out the
    whole list.

    Sort order:
      1. running cards first (most recent activity on top)
      2. blocked cards
      3. failed cards
      4. done cards (most recent on top)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not events:
        return []

    # Window the events by recency. The caller may have already done
    # this; we re-filter defensively because aggregate is the public
    # API.
    cutoff = now - timedelta(seconds=window_seconds)
    recent: list[dict] = []
    for ev in events:
        ts = _parse(ev.get("created_at"))
        if ts is None or ts >= cutoff:
            recent.append(ev)
    if not recent:
        return []

    buckets: dict[str, list[dict]] = {}
    bucket_key_to_card_id: dict[str, str] = {}
    for ev in recent:
        grouping = _grouping_key(ev)
        if grouping is None:
            continue
        family, group_key = grouping
        bucket_key = f"{family}::{group_key}"
        buckets.setdefault(bucket_key, []).append(ev)
        bucket_key_to_card_id[bucket_key] = _card_id(family, group_key)

    cards: list[ActivityCard] = []
    for bucket_key, bucket in buckets.items():
        family = KIND_FAMILY[str(bucket[0]["kind"])]
        # First/last event by id ordering (events come ASC).
        first = bucket[0]
        last = bucket[-1]
        focus = _payload_node_id(first.get("payload") or {}) or _payload_node_id(
            last.get("payload") or {}
        )
        # Severity = max across constituents.
        severity = "info"
        for ev in bucket:
            severity = _severity_max(
                severity,
                _kind_severity(str(ev.get("kind", "")), ev.get("payload") or {}),
            )
        # Status = derived from latest terminal-signal we've seen.
        status = "running"
        closed_at: str | None = None
        for ev in bucket:
            term = _terminal_state(str(ev.get("kind", "")))
            if term is not None:
                status = term
                closed_at = str(ev.get("created_at", ""))
        # If a card has not seen a fresh event in 30s, treat as quiescent.
        last_ts = _parse(str(last.get("created_at", "")))
        if status == "running" and last_ts is not None:
            if (now - last_ts).total_seconds() > 30:
                status = "done"
                closed_at = str(last.get("created_at", ""))

        # Title preference: <family> · <focus> if we have one.
        title = _title_for(family, focus, str(first.get("kind", "")))

        # Build summary lines: most recent N events, oldest→newest at
        # the bottom (matching how a reader scans top-down).
        lines: list[str] = []
        for ev in bucket[-CARD_BODY_LINES_MAX:]:
            lines.append(_line_for(ev))
        if len(bucket) > CARD_BODY_LINES_MAX:
            # Note hidden tail (rendered by widget as "▸ N earlier").
            pass

        summary_fields: dict = {}
        if family == "intervention":
            kinds_seen = sorted({str(ev.get("payload", {}).get("kind") or "") for ev in bucket})
            summary_fields["kinds"] = [k for k in kinds_seen if k]

        cards.append(
            ActivityCard(
                card_id=bucket_key_to_card_id[bucket_key],
                family=family,
                title=title,
                focus_node_id=focus,
                status=status,
                severity=severity,
                first_event_id=int(first.get("id") or 0),
                last_event_id=int(last.get("id") or 0),
                first_at=str(first.get("created_at", "")),
                last_at=str(last.get("created_at", "")),
                event_count=len(bucket),
                summary_fields=summary_fields,
                recent_event_lines=tuple(lines),
                closed_at=closed_at,
            )
        )

    cards.sort(
        key=lambda c: (STATUS_ORDER.get(c.status, 99), -c.last_event_id)
    )
    return cards


def aggregate_from_db(
    *,
    lookback: int = 500,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    now: datetime | None = None,
) -> list[ActivityCard]:
    """Convenience: pull recent events from SQLite and aggregate."""
    events = data.fetch_new_events(last_event_id=0, limit=max(1, lookback))
    return aggregate(events, now=now, window_seconds=window_seconds)


def _parse(raw) -> datetime | None:
    if not raw or not isinstance(raw, str):
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


__all__ = [
    "ActivityCard",
    "CLOSE_GRACE_SECONDS",
    "DEFAULT_WINDOW_SECONDS",
    "FAILURE_KINDS",
    "FAMILIES",
    "FAMILY_COLOR_TOKEN",
    "FAMILY_GLYPH",
    "KIND_FAMILY",
    "KIND_SEVERITY",
    "SEVERITY_COLOR_TOKEN",
    "SEVERITY_GLYPH",
    "SEVERITY_ORDER",
    "STATUS_ORDER",
    "TERMINAL_KINDS",
    "aggregate",
    "aggregate_from_db",
]


# ``json`` is imported above for future use (when cards need to
# serialise into report files / events). The exported `__all__` keeps
# the public API explicit so import * stays predictable.
_ = json  # silence unused-import lint while keeping the import live
