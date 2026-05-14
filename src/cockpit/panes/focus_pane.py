"""Focus pane — right-side widget showing the agent's current focus node(s).

Derives the focus from the cockpit_events tail (same source as the
phase strip + activity pane). Pure data flow per ADR 0007.

A node's focus *score* is

    score(node) = sum_{event ∈ window} 1.0 * exp(-age_sec(event) / 60.0)

restricted to events that name the node in their payload. The pane
shows the top-N scored nodes; when the top score is at least 2× the
runner-up the pane reports a single focused node, otherwise it
displays the top few as "divided focus" so the researcher can see the
agent is splitting attention.

Cooldown / anti-flicker
-----------------------
:func:`derive_focus` accepts the previous focus list and only swaps a
node in or out when its score crosses ±20 % of the current top. Each
1-second tick computes a fresh ``FocusState``; the cooldown keeps it
stable when scores are near each other so the user is not seeing the
top row swap every second.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import exp

from rich.console import Group, RenderableType
from rich.text import Text
from textual.widgets import Static

from cockpit import data
from cockpit.i18n import t
from cockpit.theme import color
from cockpit.theme import style as theme_style

DEFAULT_WINDOW_SECONDS = 120
DEFAULT_DECAY_SECONDS = 60.0
DEFAULT_TOP_N = 5
DOMINANCE_RATIO = 2.0
COOLDOWN_RATIO = 0.20


@dataclass(slots=True, frozen=True)
class FocusState:
    """Snapshot of "what the agent is working on right now"."""

    nodes: tuple[str, ...] = field(default_factory=tuple)
    scores: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    is_divided: bool = False
    intent: str = ""
    source_event_ids: tuple[int, ...] = field(default_factory=tuple)


_EMPTY = FocusState()


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


def _node_ids_from_event(event: dict) -> list[str]:
    """Return the node ids referenced by one event's payload.

    A single event can reference several nodes (judgement_recorded has
    winner + a + b). All count toward focus, but the winner counts a
    bit more — the multiplier is folded into the score below.
    """
    payload = event.get("payload") or {}
    candidates: list[str] = []
    for key in ("winner_node_id", "proposition_id", "draft_id", "node_id", "target"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    # Pull a/b for judgement_recorded — they participate but less than winner.
    for key in ("a_node_id", "b_node_id"):
        value = payload.get(key)
        if isinstance(value, str) and value and value not in candidates:
            candidates.append(value)
    return candidates


def derive_focus(
    events: list[dict],
    *,
    now: datetime | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    top_n: int = DEFAULT_TOP_N,
    prev: FocusState | None = None,
) -> FocusState:
    """Derive the current focus from a sequence of events.

    Pure function; the calling widget passes ``prev`` if it wants
    anti-flicker. ``now`` defaults to UTC now.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not events:
        return _EMPTY

    cutoff_age = window_seconds
    scores: dict[str, float] = {}
    source_ids: list[int] = []
    intent = ""
    explicit_focus_nodes: list[str] = []

    for ev in events:
        ts = _parse(ev.get("created_at"))
        if ts is None:
            continue
        age = (now - ts).total_seconds()
        if age > cutoff_age:
            continue
        kind = str(ev.get("kind", ""))
        payload = ev.get("payload") or {}
        weight = exp(-max(age, 0.0) / DEFAULT_DECAY_SECONDS)
        # Explicit phase_set hints: nodes listed there get an extra
        # bump (the agent told us where it is looking).
        if kind == "phase_set":
            for n in payload.get("focus_nodes") or []:
                if isinstance(n, str) and n:
                    scores[n] = scores.get(n, 0.0) + 5.0 * weight
                    explicit_focus_nodes.append(n)
            new_intent = str(payload.get("intent") or "").strip()
            if new_intent:
                intent = new_intent[:200]
            continue
        # agent_narration scope can carry a node ref.
        if kind == "agent_narration":
            scope = str(payload.get("scope") or "")
            if scope.startswith("node:"):
                node = scope[5:]
                if node:
                    scores[node] = scores.get(node, 0.0) + 1.0 * weight
            text = str(payload.get("text") or "")
            if text and not intent:
                intent = text[:200]
            continue
        ids = _node_ids_from_event(ev)
        for i, n in enumerate(ids):
            # Winner / explicit target gets full weight; subsequent ids
            # (a/b) get reduced weight so a judgement comparison doesn't
            # over-weight the loser.
            bump = weight if i == 0 else 0.4 * weight
            scores[n] = scores.get(n, 0.0) + bump
        source_ids.append(int(ev.get("id") or 0))

    if not scores:
        return _EMPTY

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    # Cooldown: keep prev's top node if the new top isn't 20%+ stronger.
    if prev is not None and prev.nodes:
        prev_top = prev.nodes[0]
        new_top, new_score = ranked[0]
        if new_top != prev_top:
            prev_score = scores.get(prev_top, 0.0)
            if prev_score > 0 and new_score < prev_score * (1.0 + COOLDOWN_RATIO):
                # Re-promote prev_top.
                ranked = [(prev_top, prev_score)] + [
                    (n, s) for n, s in ranked if n != prev_top
                ]

    top = ranked[:top_n]
    top_score = top[0][1]
    runner = top[1][1] if len(top) > 1 else 0.0
    is_divided = runner > 0 and top_score < runner * DOMINANCE_RATIO

    if is_divided:
        visible = [n for n, _ in top]
        confidence = top_score / sum(s for _, s in top)
    else:
        visible = [top[0][0]]
        confidence = top_score / sum(scores.values()) if scores else 0.0

    # Explicit focus_nodes from phase_set take precedence display-wise.
    if explicit_focus_nodes:
        visible_set = list(dict.fromkeys(explicit_focus_nodes + visible))[:top_n]
        visible = visible_set

    return FocusState(
        nodes=tuple(visible),
        scores={n: scores[n] for n in visible if n in scores},
        confidence=min(1.0, max(0.0, confidence)),
        is_divided=is_divided,
        intent=intent,
        source_event_ids=tuple(source_ids[-10:]),
    )


def derive_focus_from_db(
    *,
    lookback: int = 200,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    now: datetime | None = None,
    prev: FocusState | None = None,
) -> FocusState:
    """Convenience: read cockpit_events and derive focus."""
    events = data.fetch_new_events(last_event_id=0, limit=max(1, lookback))
    return derive_focus(
        events,
        now=now,
        window_seconds=window_seconds,
        prev=prev,
    )


class FocusPane(Static):
    """Static widget rendering the current FocusState.

    The widget caches the previous :class:`FocusState` so the cooldown
    behaviour kicks in on each refresh; the App's tick handler calls
    :meth:`refresh_focus` to recompute from the database.
    """

    def __init__(self) -> None:
        super().__init__("")
        self.id = "focus-pane"
        self.classes = "pane"
        self.lang = "en"
        self._state: FocusState = _EMPTY
        self.border_title = t(self.lang, "focus_title")
        self.shrink = True

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.border_title = t(self.lang, "focus_title")
        self._redraw()

    def set_state(self, state: FocusState) -> None:
        self._state = state
        self._redraw()

    @property
    def state(self) -> FocusState:
        return self._state

    def refresh_focus(self) -> None:
        try:
            new_state = derive_focus_from_db(prev=self._state)
        except Exception:  # pragma: no cover - defensive
            new_state = _EMPTY
        self.set_state(new_state)

    def _redraw(self) -> None:
        state = self._state
        if not state.nodes:
            self.update(Text(t(self.lang, "focus_empty"), style=color("foreground-subtle")))
            return
        lines: list[RenderableType] = []
        if state.is_divided:
            lines.append(
                Text(
                    t(self.lang, "focus_divided"),
                    style=color("warning"),
                )
            )
        max_score = max(state.scores.values()) if state.scores else 1.0
        for node in state.nodes:
            row = Text()
            score = state.scores.get(node, 0.0)
            row.append(f"{node:<20}  ", style=theme_style("kind-hypothesis", bold=True))
            bar_width = 12
            filled = int(round((score / max_score) * bar_width)) if max_score else 0
            bar = "█" * filled + "·" * (bar_width - filled)
            row.append(bar, style=color("kind-evidence"))
            row.append(f"  {score:.2f}", style=color("foreground-muted"))
            lines.append(row)
        if state.intent:
            intent_line = Text()
            intent_line.append(
                t(self.lang, "phase_intent_label") + ": ",
                style=color("foreground-muted"),
            )
            intent_line.append(state.intent, style=color("foreground"))
            lines.append(intent_line)
        self.update(Group(*lines))


__all__ = [
    "FocusPane",
    "FocusState",
    "derive_focus",
    "derive_focus_from_db",
]
