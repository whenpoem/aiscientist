# Retrospective — v4.1.0a0

> Plan v3 ship. Cockpit TUI sweeping overhaul: 4 themes (warm-dark default), 3-column adaptive layout + F-key focus mode, 3 new proof-trunk tabs (Corpus / Diagnostics / Lean), Ctrl+P command palette, 6 i18n regressions fixed with a permanent regression-test guard. Tag `v4.1.0a0` at the head of branch `claudescientist`.
>
> Tests: **302 green** (was 239 at v4.0.0a1; +63 new, none removed). Ruff clean. Schema unchanged from v4.0.0a1 (memory_mcp v5 / verify_mcp v4 / cockpit v1 / prove_mcp v4) — TUI overhaul touched no DB tables.

---

## What landed

### G1 — Design system foundation

- `src/cockpit/theme/themes.py` — 4 `Theme` objects registered with Textual's theme system: `claude-warm-dark` (default, Anthropic #d97757), `claude-warm-light`, `claude-cool-dark` (preserves the prior GitHub-dark feel for SSH/old terminals), `claude-high-contrast` (WCAG AAA).
- `src/cockpit/theme/tokens.py` — runtime accessor (`color()` / `style()` / `kind_color()`) so widgets that build Rich `Text` styles dynamically resolve from the active theme. Module-level `_CURRENT_VARS` updated by `update_theme_vars()` whenever theme switches.
- `src/cockpit/theme/cockpit.tcss` — full rewrite. Zero hex literals. Only Textual's standard `$variables` (`$primary`, `$surface`, `$panel`, `$boost`, `$foreground`, ...) so the file parses before App init has registered custom themes.
- All `modals/*.py` `DEFAULT_CSS` blocks similarly purged of hex.
- `src/cockpit/settings.py` — TOML persistence at `~/.config/claudescientist/cockpit.toml` (`%APPDATA%` on Windows). Schema-versioned. `RESEARCH_AGENT_COCKPIT_CONFIG` env override for tests.
- `T` key cycles themes; choice persists immediately.
- Tests: `test_themes.py` (16 cases), `test_settings.py` (9 cases).

### G2 — Layout v3

- `src/cockpit/layout.py` — 3 layout presets (`wide` / `narrow` / `single`) + breakpoint logic (`WIDE_MIN_WIDTH=120`, `NARROW_MIN_WIDTH=80`). The `focus` preset is a user-facing alias for `single` that always collapses regardless of width.
- TCSS rewritten with three `#body-grid.layout-*` rule sets. Compose order changed to Tree → Detail → Tabs → Events so grid auto-flow lands every pane in its right cell across all three layouts.
- `F` key toggles single-pane focus; `Esc` restores. Setting persists. Switching focused pane in single mode swaps the visible pane (no need to exit focus, change pane, re-enter).
- `App.on_resize` re-resolves layout class on every terminal-size change, with the saved preset as the upper bound (auto-collapses, never auto-promotes — preserves user intent).
- Tests: `test_layout_adaptive.py` (16 cases including 2 `App.run_test` integration cases at 160-col).

### G3 — Proof-trunk panes

- 3 new tabs added to `RightTabsPane`: **Corpus**, **Diagnostics**, **Lean**. `TAB_ORDER` is now 7 entries; cycle key (`f`) walks all of them.
- `src/cockpit/data.py` gained 3 fetchers — `fetch_corpus_problems`, `fetch_diagnostic_manifests`, `fetch_lean_attempts` — each guarded by `_table_exists` so a v3.x DB without `prv_*` tables returns `[]` instead of raising.
- Status icons: ⏳ ✓ ✗ for diagnostics; ✓ ✗ ⌛ ⏸ ▶ for Lean attempts. Translated status labels (en / zh).
- Drill-in (`Enter` on a tab row) generalized in `app._row_detail`: now handles Corpus / Diagnostics / Lean rows alongside the existing Risks / Failures / Claims / Literature kinds.
- Per-pane refresh dispatch extended for proof events: `proof_corpus_ingested` → `_refresh_corpus()`, `proof_diagnosis_*` → `_refresh_diagnostics()`, `lean_proof_*` → `_refresh_lean()`. No more full-table-scan cascade.
- ~32 new i18n keys (corpus_*, diagnostics_*, lean_*) in both en and zh.
- Tests: `test_proof_panes.py` (11 cases): empty-DB graceful, populated rows parsed correctly, dispatch routes to the right tab, drill-in produces localized detail.

### G4 — Polish + maturity

- `src/cockpit/commands.py` — Textual `Provider` subclasses register every cockpit action with the built-in command palette (Ctrl+P). `ThemeSwitcherCommands` lets users jump directly to a specific theme instead of cycling through all four. `cockpit_action_entries(lang)` is a free function so unit tests can enumerate the surface without the full Provider runtime.
- 6 i18n regressions fixed (the audit findings from `docs/retrospective-v4.0a0.md`):
  - `app.py:608` "Root cause:" → `t(lang, "failure_root_cause")`
  - `app.py:625` "Resolution:" → `t(lang, "failure_resolution")`
  - "Signature:" → `t(lang, "failure_signature")`
  - `app.py:634` "Venue:" / "Source:" → `t(lang, "lit_venue")` / `t(lang, "lit_source")`
  - "Note:" / "Source:" in claims drill → `t(lang, "claim_note")` / `t(lang, "claim_source")`
- `tests/cockpit/test_no_hardcoded_strings.py` — permanent regression guard. Scans 5 cockpit source files for the known-bad literal patterns (`"Root cause:"`, `"Venue:"`, etc.) and asserts every newly-added i18n key has both en and zh translations. Re-introduction is a CI failure.
- Tests: `test_commands.py` (4 cases), `test_no_hardcoded_strings.py` (7 cases).

---

## Final stats

| Metric | v4.0.0a1 | v4.1.0a0 | Δ |
|---|---|---|---|
| Tests | 239 | **302** | +63 |
| Cockpit test files | 3 | 8 | +5 |
| Cockpit source files | 12 | 16 | +4 |
| i18n keys (each lang) | ~140 | ~190 | +~50 |
| Hex literals in TCSS / modals / panes | 12 | **0** | -12 |
| Themes | 1 (hardcoded) | 4 (registered) | +3 |
| Layout modes | 1 (rigid 2×2) | 3 (adaptive) | +2 |
| Right-side tabs | 4 | 7 | +3 |
| Bilingual UI keys ratified | partial | full | — |

---

## Design choices worth recording

### Why `claude-warm-dark` as default

The user explicitly asked for "与 Claude Code 搭配和谐". Anthropic's brand orange (#d97757) is the obvious harmonization vector. We made it the default *but* shipped `claude-cool-dark` (the prior GitHub-dark palette) as a one-keystroke alternative — users on legacy terminals or those who want the familiar accent are not forced to relearn. T-key cycling means switching is free.

### Why 3-column wide instead of 2×2

The original 2×2 grid put **events** in the bottom-right where peripheral vision is weakest, even though events change most frequently (1-second poll). Promoting events to a full right column with row-span 2 means new events always land in the most-glanceable region. Tabs sink under detail because tabs change least often (manual interaction).

### Why F-key alias for `single` instead of a separate "focus" preset

Tested both. The user-facing F-key model is "I want to focus", not "I want layout=single". When a user F-toggles on a wide terminal, then resizes the window, they'd be surprised if focus mode collapsed to the auto-resolved layout. Treating `focus` as a preset that *always* resolves to single (regardless of width) preserves the contract.

### Why TCSS uses only Textual's standard variables

Textual parses `CSS_PATH` before `App.__init__` runs `register_theme()`. Custom variables like `$kind-hypothesis` would fail to resolve in TCSS. Two options were on the table: (a) move all custom token consumption out of TCSS into Rich Text styles via `tokens.color()`, or (b) call `register_theme()` somehow earlier. We chose (a) because it's the cleaner separation: TCSS handles structural styling (borders, layouts, padding) using Textual's well-defined palette; Rich Text rendering handles semantic styling (kind icons, status colors) via tokens. Rendering performance: the `_CURRENT_VARS` dict is in-process, dict access is O(1), no measurable overhead.

### Why command palette as additive, not replacement, for `:` mode

The `:` command mode is documented in `docs/workflows/`, has muscle memory for power users, and supports free-form arguments (`note <text>`, `pin <session> <metric> <value>`) that don't fit a fixed-action palette entry. Adding Ctrl+P provides discoverability without breaking existing workflows. Both surface the same actions; users pick whichever matches their mental model.

---

## Deferred to v4.1.0a1+ (Tier 1, ranked by impact ÷ effort)

| Item | Why deferred | Effort | Impact |
|---|---|---|---|
| **Sparklines** in BT leaderboard + Lean duration trend + held-out budget bar | Nice-to-have; the empty-state hint covers the data-discovery use case for now | 1 d | medium |
| **PaneHeader** widget (kind icon + i18n title + counter shown in border) | Border-title strings already cover the basic case via existing `set_title` methods | 0.5 d | low-medium |
| **Mouse handlers** (click pane to focus, scroll to navigate, status-bar segment clicks) | Keyboard-first remains the primary contract; mouse is purely additive | 1 d | medium |
| **Animation** (event row fade-in, modal slide-in) + reduced-motion env | Cosmetic; current paint is already fast and visually clean | 0.5 d | low |
| **Help v2 tabbed modal** | Existing single-page help is functional; tabbed version is polish | 0.5 d | low |
| **Incremental graph fetch** (`fetch_graph_delta`) | Current full fetch is O(N) per second; fine for N < 1000 | 1 d | low until N grows |
| **Detail-pane memoization** | Same as above — no measured slowness today | 0.5 d | low |

### Specifically not deferred — these are intentional v4.1 design decisions

- **No web UI** (ADR 0003 reaffirmed)
- **No new languages** beyond en/zh
- **No replacement of `:` command mode** (additive palette only)
- **No multi-user mode**
- **No force-directed graph viz**

---

## Reflection

### What worked

1. **Phased rollout (G1→G4) shipped each phase green.** Theme system landed with 25 new tests before any layout work touched the screen — no overlap-debug pain. Same for G2 → G3 → G4.
2. **Token resolver via module-level dict instead of App introspection.** Originally tried `App.get_running_app()` style lookup; switched to `update_theme_vars()` callback after the first failed test. Simpler + more testable + works pre-App-mount.
3. **Hard regression test for hardcoded strings.** Took 20 minutes to write, will save hours of "wait, why doesn't this label translate?" later. The 6 fixes from the v4.0a0 retrospective audit are now permanently locked in.
4. **Compose-order swap as the layout primitive.** Instead of explicit `column:` / `row:` placement (Textual's grid placement is order-driven, not coordinate-driven), changing compose order from Tree-Detail-Events-Tabs to Tree-Detail-Tabs-Events fixed the auto-flow for all three layouts in one shot. Less CSS, more obvious behavior.

### What didn't

1. **First TCSS rewrite tried to use custom `$border-active` / `$kind-hypothesis` variables.** Failed because Textual parses TCSS before `register_theme()` runs. Had to backtrack and split: structural CSS uses standard `$variables`; semantic colors go through `tokens.color()` at Rich Text render time. Cost ~30 min.
2. **First test for theme provider tried to instantiate `Provider(app, screen)`.** Textual's recent versions added a `match_style` kwarg requirement. Pulled `_entries` into a free function `cockpit_action_entries(lang)` so unit tests don't need the full Provider lifecycle. Cleaner anyway — the function is the single source of truth and the Provider is a thin wrapper.
3. **Default Textual `App.run_test()` size is 80×24.** First layout integration test failed because the app resolved to `narrow` instead of `wide`. Solution: pass `size=(160, 40)` explicitly. Documented in the test docstring so the next person doesn't re-trip.
4. **Initial `os.name` monkeypatch in test_settings broke pytest internals.** Tried to spoof posix from Windows; pytest then tried to construct `PosixPath` and crashed. Removed the spoofing and asserted on path components instead. Lesson: don't monkeypatch `os.name` mid-test.

---

## Closing

v4.1.0a0 is the first release where the cockpit looks like it was *designed* rather than *assembled*. Warm-dark theme is intentional; layout adapts; proof trunk has a real surface; bilingual is enforced by CI; the command palette is discoverable. The deferred items are all polish — none of them are blockers for daily use.

Next natural step is to run a real research-end-to-end (Plan v2's deferred user-owned task) on this UI to find the rough edges that automated tests can't catch. Until then, v4.1.0a0 stands.

---

*Retrospective version: 1.0 · 2026-05-07 · base commit: forthcoming · tag: `v4.1.0a0`*
