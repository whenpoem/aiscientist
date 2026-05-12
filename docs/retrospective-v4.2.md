# Retrospective — v4.2.0

> 中文版本：[retrospective-v4.2.zh-CN.md](retrospective-v4.2.zh-CN.md)
>
> v4.2 lands across four alphas: information-architecture refit
> (a1), reports infrastructure (a2), cold-start polish (a3), and the
> vector-backend foundation that arrived first (a0). Total: 559
> tests passing, ruff clean, schema migrations applied cleanly on v4.1
> upgrade.

---

## What landed

### a0 — Vector backend + wizard polish

- `OpenAIEmbedder` now accepts any OpenAI-compatible endpoint via
  `base_url` (constructor arg or `RESEARCH_AGENT_EMBED_BASE_URL`).
  The vector dimension is probed from the first response rather
  than hardcoded. DashScope, Jina, Voyage, GLM, and the openai.com
  default all work the same way.
- The default local model upgraded to `Qwen/Qwen3-Embedding-0.6B`
  for multilingual retrieval. Users who want the smaller English
  model can pin `all-MiniLM-L6-v2` via
  `RESEARCH_AGENT_EMBED_MODEL`.
- `prv_corpus_keywords` gained an `embedding_model TEXT` column
  (schema_version 4 → 5). Retrieval now filters by the full
  `(embed_backend, embedding_model, embed_dim)` triple and refuses
  cross-model mixing with a clear re-index hint.
- New `reindex_corpus` MCP tool + `scripts/reindex_proof_corpus.py`
  CLI re-encode an existing corpus after switching backend or model.
- The setup wizard now picks a provider preset (OpenAI / DashScope
  / Jina / Voyage / GLM / Other) and prompts to open the
  first-task walkthrough on completion. It also hints at
  `HF_ENDPOINT` when the chosen model needs a Hugging Face mirror.
- ADR 0010 documents the multi-provider decision.

### a1 — TUI information-architecture refit

- Tabs grouped into Cross / Empirical / Proof. `f` cycles within
  the active group; new `N` jumps to the next group's first tab. A
  group bar above the table area shows the active group.
- Detail pane rewritten on top of Textual `Collapsible`. Five
  sections (overview, BT strength, children, cross edges, related
  failures — and reports added in a2) collapse / expand
  independently. State persists in
  `CockpitSettings.detail_section_collapsed`.
- Pane-scoped key bindings: `w` (events pane only) toggles wrap;
  `i` (tree pane only) toggles compact mode. The App-level priority
  bindings for these keys are gone — pressing `w` from the tree
  pane is intentionally a no-op.
- `docs/cockpit-keys.md` is the new canonical key-by-scope map.

### a2 — Reports infrastructure

- New `cockpit.export` module with three layers: DTO (reads SQLite,
  produces dataclasses), renderer (writes markdown or HTML strings),
  pipeline (composes the layers + writes the file + indexes it).
  Five report kinds — closure, draft, diagnostic, portfolio,
  cascade — × two formats — markdown, html. ADR 0009 documents
  the decision to write files rather than embed renderers.
- `cockpit_reports` table (schema v1 → v2) indexes every generated
  file with `(file_path, kind, related_node_id, format, bytes,
  generated_by, generated_at)`. The cockpit's Reports tab (new, in
  the Cross group) reads this table.
- `e` key on a focused node opens an ExportModal — pick a kind
  (filtered to ones that apply), pick a format (`m` / `h` / `b`),
  Enter to submit. The pipeline runs, the file is written, the
  user sees a notify with the result.
- `python -m cockpit.export` exposes the same pipeline as a CLI.
- `verify_mcp.export_report` is a thin MCP facade that lets the
  reviewer agent (and writeup tooling) call the pipeline without
  importing the cockpit module. Reviewer.md adds an optional
  attach-a-closure-report step that does NOT change the hard rules
  from ADR 0006 / 0008.
- Generated files open in the user's default app via
  `os.startfile` / `open` / `xdg-open`. The cockpit never embeds a
  markdown or HTML renderer.

### a3 — Cold-start Welcome

- New `WelcomeScreen` shown once when `state.db` is empty AND
  `CockpitSettings.welcome_shown` is False. Press Enter to
  continue, `?` to open the first-task walkthrough, `q` to quit.
- `RESEARCH_AGENT_COCKPIT_WELCOME=0` suppresses the screen for
  tests + power users — and the conftest enables this default so
  the pilot tests don't have to wrestle with screen-stack ordering.

---

## Final stats

| Metric | v4.1.0a6 | v4.2.0 | Δ |
|---|---|---|---|
| Tests | 479 | **559** | +80 |
| Cockpit test files | 12 | 18 | +6 |
| ADRs | 8 | 10 | +2 |
| Schema versions (cockpit) | 1 | 2 | +1 |
| Schema versions (prove_mcp) | 4 | 5 | +1 |
| Report kinds | 0 | 5 | +5 |
| Embedding providers documented | 1 (openai.com) | 5 + Other | +5 |
| New MCP tools (verify_mcp) | 0 | 1 (export_report) | +1 |
| New MCP tools (prove_mcp) | 0 | 2 (reindex_corpus, corpus_backend_signatures) | +2 |
| Lines of TCSS | unchanged | +14 | +14 |
| i18n keys per language | ~220 | ~290 | +70 |

---

## Design choices worth recording

### Why reports as files, not a cockpit panel

ADR 0009 has the full reasoning. The short version: cockpit absorbs
live status well, document-shaped content (long drafts, side-by-side
portfolios, cascade traces) wants a real viewer. Asking the cockpit
to render both fights the TUI's natural shape. Writing markdown /
HTML files and handing the path to the user's existing tooling
sidesteps the question without reopening ADR 0003.

### Why `(backend, model, dim)` triples instead of just `(backend, dim)`

v4.1 stored only `(embed_backend, embed_dim)` per keyword row.
Once OpenAI-compatible providers entered the picture, that pair
stopped being unique — DashScope's `text-embedding-v3` and
OpenAI's `text-embedding-3-small` are both "openai backend / 1024
dim" but produce vectors that mean different things. The triple
catches the mismatch before retrieval returns garbage.

### Why pane-scoped `w` / `i` is a real behavior change

The plan accepted the muscle-memory break. The fix for users
expecting v4.1 priority behavior is to focus the events pane first
(`3` then `w`) or the tree pane first (`1` then `i`). The doc
`docs/cockpit-keys.md` and the v4.2.0 release notes both flag this.

### Why ExportModal drives kind selection but defaults format to `md`

Most exports are reviewer-facing or git-trackable. Markdown is the
better default for both. Users who want HTML press `h`; users who
want both press `b`. The default keeps the keystroke count low for
the common case.

### Why Welcome reuses the splash dismiss pattern

The splash screen's "press any key" model survived v4.1.0a6 user
testing without complaints. Reusing the same pattern (priority
bindings + on_key catch-all + a one-time persisted flag) means
users don't learn a second dismiss idiom for the second cold-start
screen.

---

## Reflection

### What worked

- **Four-alpha cadence.** Each alpha shipped green tests + ruff
  clean before the next started. The schema bumps in a0 and a2
  applied cleanly on v4.1 → v4.2 upgrade because they were tested
  in isolation first.
- **DTO / renderer / pipeline split.** Adding a new report kind in
  v4.2.x will be one new file under `dto/` and one line in
  `BUILDERS`. Adding a new format will be one new renderer class
  and one entry in `RENDERERS`. The pipeline doesn't change.
- **Conftest default-disable for new screens.** Both `splash` and
  `welcome` ship behind env-var defaults that the conftest disables
  for tests. The Welcome-specific tests opt back in explicitly.
  Cost: two extra lines in conftest; benefit: no flaky pilot tests.
- **Reading vendored docs before refactoring.** The DTO layer
  could read SQLite directly because the existing patterns in
  `cockpit.data` and `prove_mcp.tools.corpus` were stable. The
  pipeline reuses the existing `apply_schema_migration` /
  `emit_cockpit_event` helpers from `claudescientist.runtime`.

### What didn't

- **First Welcome key-handling attempt routed through
  `pilot.press('enter')`** and lost — Textual's screen-stack key
  routing in this version doesn't bubble exactly the way I
  expected. Switching the test to drive the action method directly
  is the right shape for unit-testing screen behavior anyway, but
  cost ~20 minutes of debugging first.
- **Initial schema.sql had the new index inline,** which broke the
  legacy-v4-DB migration path because the index references a column
  the migration helper hadn't added yet. Moved the index into the
  migration helper alongside the column add. Caught by
  `test_migration_adds_column_to_legacy_table` immediately.
- **First ruff-clean pass missed one E501 (long CSS line) in the
  HTML renderer.** Split the font-family rule across two lines.
  Trivial fix; the lint catch was working as intended.
- **i18n entry growth was bigger than estimated.** v4.2 added
  ~70 keys per language vs. the plan's ~80 total. Coming in under
  estimate, but each entry needed a thoughtful translation pass —
  the user explicitly asked for natural Chinese phrasing, and the
  default "translate word-for-word" instinct produces awkward
  results.

### What we explicitly didn't do

- No `claudescientist start` launcher. Removed from the roadmap
  permanently per the user's decision during planning. Two-terminal
  manual startup remains the contract.
- No web UI. ADR 0009 + ADR 0003 hold the line.
- No V5.0 mechanics (claim_facets, closure as state machine,
  cross-trunk propagation). v4.2 is the diagnostic test: if users
  press `e` often, generate closure reports, and reviewer attaches
  them — then V5.0's "claim graph as truth source" thesis gets
  evidence. If they don't, v4.x is sufficient.

---

## Where to read next

- The v4.2 plan: `C:\Users\whenpoem\.claude\plans\iridescent-snuggling-matsumoto.md`
- ADR 0009: [`adr/0009-reports-as-files-monitoring-as-tui.md`](adr/0009-reports-as-files-monitoring-as-tui.md)
- ADR 0010: [`adr/0010-multi-provider-embeddings.md`](adr/0010-multi-provider-embeddings.md)
- Key map: [`cockpit-keys.md`](cockpit-keys.md)
- Provider preset table: [`embedding-providers.md`](embedding-providers.md)

---

*Retrospective version: 1.0 · 2026-05-11 · tag: `v4.2.0`*
