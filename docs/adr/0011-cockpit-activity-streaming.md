# ADR 0011: Cockpit activity streaming (v5.0)

- **Status**: Accepted (v5.0)
- **Date**: 2026-05

## Context

The v4.x cockpit's primary visual surface was an ``EventStreamPane`` that
listed every emitted ``cockpit_events`` row chronologically. The pane
accumulated 28+ distinct event kinds across two trunks (empirical and
proof) plus shared infrastructure, and roughly a third of those kinds
had no explicit formatter — their payloads rendered as raw
``str(payload)`` dicts. The result: opening the cockpit answered
**what atomic operations just fired** but not **what is the agent
doing right now**, **does anything need intervention**, or **what just
changed at the research level**. Multiple feedback notes flagged this
as "I can read every line but I cannot read the page".

v5.0 reframes the cockpit as a **research-action monitor** in the
style of recent "vibecoding" UIs that show the AI's work in
human-meaningful units. The change is presentation-only — no new
tables, no schema migration, no new cross-trunk coordination. The
underlying ``cockpit_events`` table and its emission contract stay
identical; only the cockpit's reading/rendering layer changes.

Three constraints anchored the design:

- **ADR 0007** requires that workflow state be *inferred from data*,
  not stored in a state machine. Phase / focus / activity cards must
  all be pure functions over the recent events tail.
- **ADR 0008** locks in exactly four cross-trunk cooperation
  interfaces; this change must not introduce a fifth.
- **ADR 0001** requires single-SQLite-file state; no socket / shared
  memory / second database.

## Decision

Restructure the cockpit into a five-layer information surface, all
derived from ``cockpit_events`` plus two new optional atomic MCP tools
that emit descriptive (non-blocking) events.

1. **Phase strip** (top dock): single-row summary showing the
   derived current phase (one of eight: ``idle / explore / select /
   experiment / verify / prove / review / narrate``), the current
   focus node, and the most recent intent. Derived by
   ``cockpit.phase.derive_phase`` from the last 200 events; idle
   threshold 90 s; anti-flicker requires ≥2 same-phase events to
   switch out of idle. The user can hide the strip with ``P``;
   persisted in ``CockpitSettings.phase_strip_visible``.

2. **Activity pane** (grid main, replaces the v4 EventStreamPane in
   column 3 of the wide layout): a vertical scroll of Rich-panel
   cards. Each card is one research action — a BT tournament, a
   proof diagnose loop, a Lean attempt — built by
   ``cockpit.activity.aggregate`` which groups events by
   ``(family, focus_node_id)`` or ``(family, 60-second bucket)``.
   Severity rolls up to the maximum of constituent events;
   ``budget_exceeded`` and ``prov_dag_stale`` are critical
   singletons. Status transitions through running / done / failed /
   blocked based on terminal kinds.

3. **Focus tab** (first tab in RightTabsPane): a derived DataTable
   showing the top scored mem_node(s) the agent is working on.
   Scoring is exponential time-decay; cooldown prevents ±20 % score
   churn from flipping the top entry every tick.

4. **Audit log** (bottom dock, collapsed): the original
   EventStreamPane preserved verbatim, demoted to a 6-row strip
   that expands to full height with ``A``. Power users keep their
   chronological event view; the eleven previously-untyped event
   kinds gain explicit formatters in
   ``events_pane._summarize``.

5. **Two new MCP atomic tools** in the cockpit MCP server:
   - ``cockpit__set_phase(phase, focus_nodes, intent)`` — emits
     a ``phase_set`` event that overrides derivation. Validates
     ``phase`` against the eight-phase vocabulary, limits
     ``focus_nodes`` to 8 with a regex check, truncates ``intent``
     to 200 chars.
   - ``cockpit__narrate(text, scope)`` — emits an
     ``agent_narration`` event. Text 1-500 chars; scope is
     ``session`` / ``node:<id>`` / ``branch:<id>``. Does NOT
     change the derived phase — narration is the soft
     inner-monologue channel.

Both tools are descriptive: the cockpit ignores agents that never
call them and falls back to derivation. The ``research-sop`` and
``prove-sop`` skills add a one-line suggestion at decision branch
points ("optionally narrate"); per ADR 0007 the SOPs remain
non-binding.

Settings additions: ``phase_strip_visible`` (default ``True``,
toggled by ``P``); ``animations_enabled`` (default ``True``,
toggled by ``M`` for SSH / tmux). Saved
``focused_pane="events"`` from pre-v5 installs is healed to
``"activity"`` at boot, mirroring the existing
``LAYOUT_FOCUS → wide`` healing pattern.

## Consequences

### Positive

- The first three seconds of opening the cockpit answer the three
  questions the surface should answer (what now / wait or
  intervene / what changed). The eleven previously-untyped event
  kinds — including the user-blocking ``budget_exceeded`` — now
  have readable summaries.
- No schema migration, no new tables, no new cross-trunk
  interface. Old ``state.db`` files load unchanged; the cockpit
  re-derives meaning each tick.
- ADR 0007's layering doctrine is reinforced: phase / focus /
  activity cards are textbook "workflow state inferred from data"
  — three pure functions over the same recent-events window.
- ``set_phase`` / ``narrate`` give SOP authors a sanctioned way
  to surface decision context without inflating the event vocab
  or coupling to the cockpit's rendering details.

### Negative

- The cockpit now does three derivations per tick instead of one
  raw-event append. Cost is bounded by ``idx_cockpit_events_created_at``
  + the 200-event window; measured well under 5 ms per tick on
  laptop-class disks.
- Test count grows ~40 tests (phase / activity / focus derivation
  + MCP tool validation + the v5-vs-v4 healing tests). The
  baseline went from 589 to 638 collected tests.
- The audit log moves to a less-prominent surface. A power user
  who relied on the event stream as their primary view loses
  centre stage; ``A`` is the recovery affordance, documented
  in ``docs/cockpit-keys.md``.
- Two new MCP tools enlarge the visible tool surface. Mitigated
  by whitelisting them only on the worker subagents
  (researcher / engineer / prover); reviewer / verifier /
  budgeter / librarian stay unchanged.

### Alternatives considered

- **Add Activity as a fourth grid column** — lost on layout
  math. Reasonable readable widths require ≥30 cols per pane;
  a fourth column needs ≥150-col terminals, well above the
  120-col wide-mode breakpoint we already commit to.
- **Replace event stream entirely, no audit log** — lost
  because long debugging sessions still need the raw firehose.
  Demoting to a collapsible bottom strip costs almost nothing
  and respects power-user habits.
- **Persist phase / focus to new tables** — lost on ADR 0007.
  The 90-second idle window plus 30 min activity window are
  defensibly "current state", and pure derivation keeps the
  v4 → v5 round-trip lossless.

## References

- Sister ADRs: [`0007-tools-skills-hooks-layering.md`](0007-tools-skills-hooks-layering.md)
  and [`0008-two-trunk-domain-architecture.md`](0008-two-trunk-domain-architecture.md).
- Code that depends on this decision:
  - ``src/cockpit/phase.py`` — phase derivation
  - ``src/cockpit/activity.py`` — card aggregation
  - ``src/cockpit/panes/phase_strip.py``
  - ``src/cockpit/panes/activity_pane.py``
  - ``src/cockpit/panes/focus_pane.py``
  - ``src/cockpit/panes/tabs_pane.py`` — Focus tab integration
  - ``src/cockpit/mcp_server.py`` — ``set_phase`` + ``narrate``
  - ``src/cockpit/app.py`` — compose + actions + healing
  - ``src/cockpit/theme/cockpit.tcss`` — ``#phase-strip`` +
    ``#events-pane.audit-log`` rules
  - ``src/cockpit/settings.py`` — new ``phase_strip_visible``
    and ``animations_enabled`` fields
  - ``src/cockpit/i18n.py`` — phase / focus / activity / audit
    log keys for en + zh
- Skills updated: ``.claude/skills/research-sop/SKILL.md``,
  ``.claude/skills/prove-sop/SKILL.md``.
- Agents updated: ``.claude/agents/researcher.md``,
  ``engineer.md``, ``prover.md``.
