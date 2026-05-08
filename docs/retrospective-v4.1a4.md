# Retrospective — v4.1.0a4

> 中文版本: [retrospective-v4.1a4.zh-CN.md](retrospective-v4.1a4.zh-CN.md)
>
> Cockpit TUI second-pass refit. The first pass (v4.1.0a0) shipped a designed-from-scratch UI; this pass closes the gaps that only show up under real use — content silently truncated, modals that swallow keys, no path to read long content, AI-flavored copy. Eight visual sub-items, six interaction fixes, and a full preview / drill-in screen architecture. **Tests: cockpit + e2e 148 / repo-wide 370 — all green** (cockpit + e2e was 89 pre-change; +59 new). Ruff clean. Schema unchanged from v4.1.0a0 — no MCP / hook / DDL touched.

---

## What landed

### Stage 0 — De-AI'd user-facing copy

`research-cockpit` / `研究座舱` and `cockpit events` / `cockpit 事件` were the four places where the project's marketing word leaked into the running UI. Replaced with neutral phrasing the user picked: `research state` / `研究状态`, `No events yet.` / `暂无事件。`. Test assertions updated in two files; the regression guard at [tests/cockpit/test_no_hardcoded_strings.py](../tests/cockpit/test_no_hardcoded_strings.py) untouched (it scans for *known-bad* literals, of which `cockpit` was not one).

### Stage 1 — Visual polish (8 sub-items)

| # | What | File |
|---|---|---|
| 1.1 | `RichLog(wrap=True)` default + `w` toggle, persisted | [events_pane.py:19](../src/cockpit/panes/events_pane.py:19) |
| 1.2 | 8 kind glyphs upgraded ASCII → Unicode (`◇▲▣•★■△▴`) + `✗` for refuted | [i18n.py:486](../src/cockpit/i18n.py:486), [tree_pane.py:201](../src/cockpit/panes/tree_pane.py:201) |
| 1.3 | Tree label compact mode (no BT/Elo) default + `i` toggle, persisted | [tree_pane.py:163](../src/cockpit/panes/tree_pane.py:163) |
| 1.4 | DataTable `[:48]` / `[:56]` hard truncation → typographic `…` ellipsis with bumped widths (64 / 72) | [tabs_pane.py:_truncate](../src/cockpit/panes/tabs_pane.py) |
| 1.5 | Status-bar heartbeat dot (●/○ based on event freshness) + intervention queue toast | [app.py:_format_last_event, _track_intervention](../src/cockpit/app.py) |
| 1.6 | Tree pane border title shows `· N active / M refuted` counts | [tree_pane.py:set_counts](../src/cockpit/panes/tree_pane.py) |
| 1.7 | BT strength mini bar in detail pane (`bt: +0.34 [───▮──────] ±0.18 n=12`) | [details.py:_bt_line](../src/cockpit/details.py) |
| 1.8 | Held-out budget progress bar (`imagenet ▓▓▓▓░░ 4/10`) in HUD + risks table | [app.py:_format_heldout](../src/cockpit/app.py), [bars.py](../src/cockpit/bars.py) |

New module: [`cockpit/bars.py`](../src/cockpit/bars.py) with `progress_bar()` and `strength_bar()` glyph builders, kept out of `i18n.py` because bars are not localized.

### Stage 2 — Interaction fixes (6 sub-items)

| # | What | File |
|---|---|---|
| 2.1 | Help modal: only `escape / enter / space / ?` dismiss; everything else `event.stop()` so a stray key during a peek can't trigger a destructive cockpit action | [help.py](../src/cockpit/modals/help.py) |
| 2.2 | Command-line per-mode draft buffer survives Esc / re-open via `:`; cleared on submit | [app.py:_show_command_line](../src/cockpit/app.py) |
| 2.3 | `<` / `>` nudge wide-layout tree column (subpreset -1/0/+1, persisted; narrow / single layouts toast a hint instead) | [layout-wide TCSS classes](../src/cockpit/theme/cockpit.tcss), [app.py:action_shrink_tree](../src/cockpit/app.py) |
| 2.4 | `u` rolls back the most recent intervention if `delivered_at IS NULL`; refuses with a "too late" toast otherwise. Refute / pin (which mutate non-intervention tables) clear the undo pointer so they're never spuriously rolled back | [data.py:undo_intervention](../src/cockpit/data.py), [app.py:action_undo_intervention](../src/cockpit/app.py) |
| 2.5 | `Tab` / `Shift+Tab` priority=True so they cycle panes from inside DataTable. Modal forwarding routes Tab to `top.focus_next()` so PinMetricModal / TextInputModal field cycle still works | [app.py:action_focus_next_pane](../src/cockpit/app.py) |
| 2.6 | `:goto <id>` jumps tree focus by exact id or unique prefix; ambiguous → warning toast lists candidates | [app.py:_goto_node](../src/cockpit/app.py) |

### Stage 3 — Preview + drill-in screen

The defining shape change of this release. List-style panes (tree / events / tabs) now offer two depths of detail:

1. **Preview** — main detail pane updates as the cursor moves (unchanged from v4.1.0a0)
2. **Full read** — Enter pushes a [DetailScreen](../src/cockpit/screens/detail.py) covering the whole window, with `h / l` to walk siblings, `j / k` to scroll, action keys (`y / n / r / c / m / p / H`) still routed by the App. Esc / `q` pops back.

Three sources implement the `DetailSource` Protocol:
- `NodeDetailSource` — walks the visible node-id list; takes a graph **callable** (not a snapshot) so action-key mutations refresh the screen on the next paint.
- `TabRowDetailSource` — re-uses the App's existing `_row_detail` builder for all 7 tab kinds (risks / failures / claims / literature / corpus / diagnostics / lean) — zero duplicated rendering logic.
- `EventDetailSource` — pretty-prints the event payload as JSON.

Render builders moved into [`cockpit/details.py`](../src/cockpit/details.py) so the main detail pane and the full-screen viewer share `node_detail_text()` exactly.

### Stage 4 — Cross-stage review fixes

Three latent bugs surfaced during the post-stage review and were closed:

1. **Priority letters eat Input keystrokes.** `L`/`T`/`F`/`w`/`i`/`u`/`q` were `priority=True` for visibility from inside DataTable focus, but in modal Inputs they ate the user's typed character. Fix: each priority-letter handler calls a `_yield_priority_letter_to_input()` helper that detects a focused Input and inserts the literal character via `insert_text_at_cursor`, returning early so the toggle doesn't fire.
2. **DetailScreen content stale after action.** After `y` inside a DetailScreen, the App refreshed the main graph but the screen kept rendering the pre-action body. Fix: `NodeDetailSource` now takes a graph callable, and `refresh_state()` repaints the top DetailScreen at the end.
3. **DetailScreen pop forgot navigation.** Walking with `l` to a sibling and pressing Esc returned the user to the original tree cursor. Fix: `action_pop_detail` calls `tree_pane.select_node_id(...)` with the source's current node id before popping.

---

## Final stats

| Metric | v4.1.0a0 | v4.1.0a4 | Δ |
|---|---|---|---|
| Tests (cockpit + e2e) | 89 | **148** | +59 |
| Repo-wide test count | — | **370** | — |
| New test files | 0 | 3 | +3 |
| Cockpit source files | 16 | 19 | +3 (`bars.py`, `details.py`, `screens/`) |
| i18n keys (each language) | ~190 | ~220 | +~30 |
| Public Screen kinds | 1 (modals only) | 2 (modals + DetailScreen) | +1 |
| Visual primitives | 0 | 2 (progress, strength bars) | +2 |
| Hex literals in TCSS | 0 | 0 | — |
| Cockpit DDL changes | 0 | 0 | — |
| Hook contract changes | 0 | 0 | — |

---

## Design choices worth recording

### Why a separate `details.py` between panes and screens

Originally `NodeDetailPane.update_for_node` carried the entire node-detail layout: short-id formatting, BT bar, parent / children rendering, cross-edge listing. When the DetailScreen needed the same content, the temptation was to either extend the pane class or copy/paste. Both were wrong.

The fix is `cockpit.details` — a free-function module that takes a `(GraphSnapshot, node_id, lang)` tuple and returns `(title: str, body: Text)`. Both consumers (pane + screen) pass through it. Unit tests for `node_detail_text` need no Textual lifecycle. Adding a new consumer (e.g. an export-to-markdown command in the future) is one import.

### Why `priority=True` on letter bindings + Input forwarding

The v4.1.0a0 retrospective documented the trade-off: priority=True so DataTable doesn't shadow the binding when the user is in tabs pane. But the consequence — typing a capital `L` inside PinMetricModal switches the language — was the kind of bug only real use surfaces. Removing priority would re-introduce the v3.x bug where `L` "seems dead" inside tabs.

The middle path: keep priority, but in each handler, check `isinstance(self.focused, Input)` and if so, use `Input.insert_text_at_cursor(literal)` to type the character that the priority binding stole. The user gets both behaviors at once: toggle from anywhere except an Input, type the character when an Input has focus.

This is a workaround, not a fix; Textual doesn't expose a "priority but yield to Input" knob. If it ever does, this can collapse to `priority=True, yield_to_input=True` on the Binding constructor.

### Why DetailScreen has its own `_paint()` instead of overriding `_render()`

Textual's `Widget._render()` returns a `Visual` and is part of the rendering pipeline. Naming a custom redraw method `_render()` (matching the pane convention from v4.1.0a0) accidentally overrides this and returns `None`, crashing the screen with a `NoneType.render_strips` error. Renamed to `_paint()` to keep the surface clear. A comment in [`detail.py`](../src/cockpit/screens/detail.py) documents the rationale so the trap doesn't recapture the next contributor.

### Why `q` pops a screen instead of always quitting

The plan-as-spec had `q` exit the app on the main screen and pop a modal / DetailScreen everywhere else. Implementing that means the priority `q` binding now fires `pop_screen()` when `screen_stack > 1`. This survived the review because the symmetry pays for itself: users learn one key (`q` = "back / leave"), modal flows feel faster than `Esc` for keyboard-only users, and the main-screen invariant (`q` = quit) is preserved by the explicit `len(screen_stack) > 1` check.

The Input-focused yield (see above) means typing the literal `q` inside an Input still works; the priority binding doesn't intercept text input.

### Why a `graph_provider` callable instead of a snapshot

The first version of `NodeDetailSource` held a `GraphSnapshot` reference at construction. After the user pressed `y` inside a DetailScreen, the App's `refresh_state()` rebuilt `self.graph` (a new GraphSnapshot object) — but the source still pointed at the old one. The screen kept showing the pre-action node state.

Switching to a callable (`lambda: self.graph`) gives the source the freshest snapshot on every `current()` call. The cost is a method call per repaint; the saving is correctness. Tests `test_node_detail_source_reads_fresh_graph_each_call` lock this behavior.

---

## Deferred — explicitly out of scope this round

These were on the original idea list but the user confirmed not in this release:

- **Sparkline rhythm strip** (roadmap Direction 7) — high value but new rendering primitive
- **Multi-select visual mode** for batch approve / reject
- **OSC 52 copy-to-clipboard**
- **Terminal title with live state**
- **Paused-subtree dim** (whole subtree dimmed when parent is paused)
- **30-line preview-mode truncation in main detail pane** — drill-in handles the long-content case so the preview pane can stay full-fidelity
- **Subscription-based DetailScreen refresh** — current solution polls on `refresh_state()`; a Textual reactive watcher could be cleaner but adds machinery for marginal gain

Anything touching schema, hooks, or MCP servers is out of scope by design — this release stays UI-only.

---

## Reflection

### What worked

1. **Phasing.** Stages 0 → 1 → 2 → 3 each landed green before the next started. Stage 3 (the structural change) sat on top of a fully-verified base, so when the priority-binding regressions surfaced they were obviously stage-3 fault, not interactions with stage 1/2.
2. **Free-function detail builders.** `details.py` was the smallest possible refactor (no class hierarchy, no protocol on the rendering side, just `(args) → (title, body)`). It's already paid back in test simplicity (assertions on `body.plain`) and is the natural extension point if a future export feature needs the same content.
3. **Regression tests for forwarding bugs.** Every priority-binding fix landed with a test that exercises the exact key sequence in the exact context. `test_priority_letters_yield_to_input_focus` and `test_enter_inside_text_input_modal_submits_value` lock in the right behavior; if a future contributor flips a binding back to non-priority or removes the yield helper, CI fails immediately.
4. **Confirming the rename through `AskUserQuestion`.** Naming is taste; surfacing the candidates and recording the user's pick avoided the rework loop.

### What didn't

1. **Naming the screen redraw `_render()`.** Lost ~20 minutes to a `NoneType.render_strips` error before noticing the override. Documented in the file comment so it doesn't bite again.
2. **First DetailScreen CSS used `dock: top` / `dock: bottom`.** Crashed render with the same null-visual symptom for a different reason — Textual's docked-children layout interaction with Screen base. Switched to vertical layout with explicit `1fr` height and it composed cleanly.
3. **Initial `priority=True` on Tab without modal forwarding.** Broke PinMetricModal field cycle. Caught by `test_cockpit_app_smoke` immediately — the test that walks p / Tab / Tab / Tab through the metric modal flow. The forwarding fix took 4 lines + a comment.
4. **Initial Enter priority forwarding wasn't async-aware.** `Input.action_submit` is a coroutine in current Textual; my forward called it without `await`, producing `RuntimeWarning: coroutine ... was never awaited` and the input never submitted. Fixed by making the App action async and `await`-ing forwarded coroutines.

### One mid-flight finding worth flagging for v4.2

`EventDetailSource` walks the events pane's `_rows` private attribute. Same pattern for tabs (`_filtered_rows`). It works; the rows are simple lists. But it's an abstraction leak — both panes should expose a `current_rows() -> list[dict]` public method. Not blocking, not in scope, but worth picking up next time these panes get touched.

---

## Closing

v4.1.0a4 is the patch where the cockpit shifts from "designed" to "feels like it was used by someone before you got here". The drill-in screen closes the only major UX gap the v4.1.0a0 retrospective listed under deferred items (long-content readability). The de-AI'd copy is a small change with a real perceptual lift. Everything else is the kind of small frictions that only show up after the first session — and they're the ones worth fixing.

The schema is untouched; the hook contract is untouched; the public MCP surface is untouched. This patch's blast radius is the cockpit's own keystrokes and pixels.

---

*Retrospective version: 1.0 · 2026-05-08 · base commit: pending · tag: `v4.1.0a4`*
