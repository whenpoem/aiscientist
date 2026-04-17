# Plan: Research-Agent Augmentation Layer — v0.2

> **Status**: detailed executable plan, v0.2 scope = TUI cockpit migration + full v0.2 roadmap (seed_perturb, research-taste, held-out budget).
> **Target machine**: Windows 11, project at `D:\aiscientist\claudescientist` (v0.1 already shipped).
> **Principle (unchanged)**: Claude Code stays untouched. All contributions plug in around it.
>
> **Locked decisions for v0.2**:
> - **UI**: Textual-based TUI replaces React/FastAPI WebUI. **No browser, no Vite, no uvicorn, no port 7777.**
> - **Cockpit-MCP transport**: stdio (same as memory/verify). Settings.json drops the HTTP entry.
> - **DAG view**: Textual Tree as navigation spine + detail panel for cross-edges (no 2D ASCII layout).
> - **v0.2 scope**: TUI + seed_perturb + research-taste + held-out budget (4 work-streams, ~3 weeks).
> - **Plan artefact**: this plan is also copied to `D:\aiscientist\claudescientist\docs\plan-v0.2.md` as Step 0 of execution.

---

## 1. Context

v0.1 shipped a working stack (memory-mcp + verify-mcp + 5 hooks + 5 subagents + 3 skills + WebUI cockpit) and passed all 20 tests. Two problems became obvious in real use:

1. **The WebUI is over-engineered for the actual workload.** The cockpit shows ~20 hypothesis nodes, ~50 failures, a small event stream, and one intervention form. To render that, v0.1 runs FastAPI + uvicorn + WebSocket + React 19 + Vite 8 + Tailwind v4 + @xyflow/react — three layers of build/runtime, two extra processes you have to remember to start, and one mounting bug (`app.mount("/", mcp_http_app)` masks 404s, see v0.1 review). Subjectively the user reported "架构不稳定 / 重 / 不协调".
2. **v0.2 roadmap from v0.1 was deferred indefinitely.** Seed-perturb verification, research-taste / Elo selection, and held-out budget enforcement were all listed as "v0.2+" without dates. With v0.1 stable, now is the right time to commit them.

This plan addresses both. The TUI migration is the largest piece (~50% of effort) but has the highest user-experience leverage. The three roadmap items unlock the comparison-against-EvoScientist publishing target listed in v0.1 §7.6.

The deliverable is a v0.2 cockpit a single researcher can use in two terminals (Claude Code on the left, TUI on the right) with no browser involved, plus the verification + research-taste capabilities that make our memory layer measurably different from EvoScientist.

---

## 2. Tech Term Primer (only what's new since v0.1)

### 2.1 TUI / Textual

**TUI**: a full-screen, keyboard-driven application that paints inside a terminal. Examples: `lazygit`, `k9s`, `htop`, `btop`, `neomutt`. No mouse required (though Textual supports one); no GPU; runs over SSH.

**Textual**: the dominant Python TUI framework, written by the author of Rich. Current 8.2.3 (April 2026). Key concepts we'll use:

- **Widget tree + CSS**: the layout is a tree of `Widget` subclasses, styled with a CSS-like file (`*.tcss`). Borders, padding, grid columns, colors all in CSS.
- **Reactive state**: `selected_node = reactive(None)` at class level; assigning to it auto-triggers `watch_selected_node(old, new)` and re-renders dependents.
- **Workers**: `@work(exclusive=True, thread=False)` runs an async coroutine off the main loop. Used for the SQLite tail.
- **Messages**: widgets emit typed messages (e.g. `Tree.NodeSelected`); the App handles them in `on_tree_node_selected`. This is the keyboard/click event pipeline.
- **Modals**: `class HelpScreen(ModalScreen[None])` + `await self.push_screen_wait(HelpScreen())` for confirmations and dialogs.
- **Bindings**: a class-level `BINDINGS = [Binding("q", "quit", "Quit"), ...]` list. Textual auto-renders the bindings as hint chips in the `Footer` widget — exactly what k9s/lazygit users expect.

### 2.2 Why kill FastAPI

The cockpit's REST + WS layer existed only because the React frontend needed an HTTP origin. With the TUI we can:

- Open the same SQLite file directly (`runtime.connect_sqlite()` already exists in `src/claudescientist/runtime.py`).
- Run cockpit-MCP as **stdio** under Claude Code's MCP launcher, exactly like `memory` and `verify`. No port, no `app.mount` bug, no CORS, no separate uvicorn process to remember to start.
- Use a single 1-second `SELECT id > last_seen FROM cockpit_events` poller in the TUI. WAL mode means it never blocks the writer.

Net deletion: ~240 lines (`src/cockpit/server.py`) + the entire `src/cockpit/frontend/` tree (~2.5k LOC + node_modules).

### 2.3 seed_perturb / baseline_fairness (verify-mcp additions)

**seed_perturb**: re-run a training script with N different random seeds (`--seed 0/1/2`), compute mean/std of the reported metric. Catches "lucky single seed" results that EvoScientist papers occasionally publish. Implementation: subprocess runner, no model assumptions.

**baseline_fairness**: given two run logs, compare hyperparameter budget (epochs × lr-trials × #params). Flags cases where the proposed method got 10× the search budget vs. the baseline. Implementation: log parser + ratio threshold.

### 2.4 Research-taste skill / Elo selection

**Elo selection**: when the researcher subagent proposes K candidate hypotheses, run pairwise comparisons in a small "judge" loop (the same model, no extra agents) and assign Elo scores. Pick top 1–2. This is how Tournament-of-Reasoning and AlphaCode rerankers work. Replaces the v0.1 "pick the first one" behavior.

### 2.5 Held-out budget enforcement

A small SQLite table + CLI tool. `register_heldout_dataset` moves data out-of-tree into `~/.research-agent/heldout/<name>/` and writes a manifest hash. `query_heldout(dataset, model, budget_units)` returns predictions but decrements a budget counter (default: 5 query-batches per dataset per project lifetime). If the manifest hash drifts, all queries hard-fail. This is the only way to prevent slow-leak overfitting to the test set across many sessions.

---

## 3. v0.2 Architecture (delta from v0.1)

```
┌──────────────────────────────────────────────────────────────────┐
│  Terminal A (left half of screen)                                │
│    claude  ──  Claude Code REPL                                  │
│       │                                                          │
│       │ stdio                                                    │
│       ▼                                                          │
│    memory-mcp ─┐                                                 │
│    verify-mcp ─┤  ───── all read/write ─────► state.db (SQLite)  │
│    cockpit-mcp ┘                                                 │
│                                                                  │
│  Terminal B (right half of screen)                               │
│    uv run python -m cockpit.tui                                  │
│        ├─ tail cockpit_events  ◄─── (1s poll, WAL mode)          │
│        ├─ read mem_nodes / mem_edges / mem_failures / ver_*      │
│        └─ write cockpit_interventions  (POST equivalent)         │
└──────────────────────────────────────────────────────────────────┘
```

**What disappeared**: uvicorn process, port 7777, FastAPI app, WebSocket, the entire `src/cockpit/frontend/` tree, the cockpit's HTTP-MCP transport entry in settings.json.

**What stayed**: the data contract. `cockpit_events` and `cockpit_interventions` schemas are unchanged. Hooks (`intervention_pump.py`, `stop_flush.py`) are unchanged. The TUI is purely a new view + writer over the same SQLite tables.

---

## 4. TUI Design (the meat)

### 4.1 Screen layout

```
┌─ research-cockpit  state.db: 23 nodes · 7 failures · 412 events ─ 14:32 ─┐
│ ┌─ 1 Hypothesis Tree ──────────┐ ┌─ 2 Node Detail ──────────────────────┐ │
│ │ ▾ Q  Why does ViT scale poo… │ │ H_07  hypothesis  state: active      │ │
│ │   ▾ H_07 dropout-rate hurts… │ │ ───────────────────────────────────  │ │
│ │     ▸ E_12 mnist-proxy fail  │ │ Per-head dropout 0.3 reduces test    │ │
│ │     ▸ E_15 cifar-proxy ok    │ │ accuracy by 1.8pp on CIFAR-10 with   │ │
│ │   ▾ H_08 attention-pattern…  │ │ ViT-S/16. p=0.04, n=3 seeds.         │ │
│ │     ▸ E_18 attn-mass         │ │                                      │ │
│ │   ▸ H_09 init-scale          │ │ Parents:  Q (root)                   │ │
│ │ ▸ Q  follow-up: optimizer…   │ │ Children: E_12, E_15                 │ │
│ │                              │ │ Cross-edges: ⇄ H_08 (contradicts)    │ │
│ │                              │ │ Evidence: 2 attached, 1 refutes      │ │
│ └──────────────────────────────┘ └──────────────────────────────────────┘ │
│ ┌─ 3 Event Stream ─────────────┐ ┌─ 4 Failures │ Claims │ Literature ──┐ │
│ │ 14:32:11  graph_delta H_09…  │ │ # trigger          symptom    seen  │ │
│ │ 14:31:58  failure_added f_7  │ │ 7  fit_on_concat   leakage    3     │ │
│ │ 14:30:02  turn_end Δ +2/−0   │ │ 5  rm_dataset      destroy    1     │ │
│ │ 14:28:44  intervention reje… │ │ 3  oom_batch_size  crash      8     │ │
│ │                              │ │ 1  cuda_oom        crash      12    │ │
│ └──────────────────────────────┘ └──────────────────────────────────────┘ │
│ :reject H_07 weak evidence on cifar                                       │
└── j/k nav · y approve · n reject · / filter · ? help · q quit ───────────┘
```

**Grid (Textual CSS)**: 2 rows × 2 cols inside an outer column with header (1 row) and footer (1 row). The bottom row is overridden by the command line when `:` is pressed.

**Pane numbering**: 1=tree, 2=detail, 3=events, 4=right tabs (Failures/Claims/Literature). Press `1`–`4` to focus.

### 4.2 Interaction modes

| Mode | Entered by | Purpose |
|---|---|---|
| **Normal** (default) | (always) | Navigate, toggle, fire one-key actions |
| **Command** | `:` | Type a free-form intervention, like vim |
| **Filter** | `/` | Filter the focused pane's rows |
| **Modal** | `?`, `H`, `p`, `m` | Help, halt-confirm, pin-metric form, mark-refuted-confirm |

Pressing `Esc` always returns to Normal.

### 4.3 Keybindings (full table)

#### Navigation (Normal mode)

| Key | Action |
|---|---|
| `j` / `k` | Move down / up in the focused pane |
| `h` / `l` | Collapse / expand tree node (in pane 1); else move focus left/right |
| `g` / `G` | Jump to top / bottom of current pane |
| `Ctrl-D` / `Ctrl-U` | Half-page down / up (long event streams) |
| `Tab` / `Shift-Tab` | Cycle focus to next / previous pane |
| `1` / `2` / `3` / `4` | Jump focus to pane N |
| `f` | (in pane 4) cycle Failures → Claims → Literature → Failures |
| `Enter` | Drill into selected row (open evidence detail, expand failure, etc.) |
| `Esc` | Cancel input / close modal / clear filter / return to Normal |

#### One-key actions on focused hypothesis (Normal mode)

| Key | Action | Writes |
|---|---|---|
| `y` | Approve this hypothesis | `cockpit_interventions(kind="approve", target=node_id, payload="")` |
| `n` | Reject this hypothesis | `cockpit_interventions(kind="reject", target=node_id, payload="")` |
| `r` | Redirect (opens single-line input for redirect text) | `cockpit_interventions(kind="redirect", target=node_id, payload=<input>)` |
| `c` | Constrain (opens single-line input) | `cockpit_interventions(kind="constrain", target=node_id, payload=<input>)` |
| `m` | Mark as refuted (opens confirm modal) | `mem_nodes.state = 'refuted'` via cockpit-mcp tool |
| `p` | Pin metric (opens form modal: dataset / metric / value) | `ver_metric_pins` row via cockpit-mcp tool |
| `H` | **Halt agent** (capital H, opens confirm modal) | `cockpit_interventions(kind="halt", target=NULL, payload=<reason>)` |

The capital `H` for halt is deliberate (lazygit uses capital letters for destructive actions). Confirm modal requires typing `y` to actually fire.

#### Views & meta (Normal mode)

| Key | Action |
|---|---|
| `/` | Enter Filter mode for current pane |
| `?` | Open help overlay (modal showing all bindings) |
| `:` | Enter Command mode (free-form intervention input) |
| `t` | Toggle timestamp format in event stream (relative ↔ absolute) |
| `s` | Toggle "show refuted" in tree (default: hidden, dimmed-strikethrough when shown) |
| `R` | Force refresh all panes from SQLite (no-poll wait) |
| `Ctrl-L` | Clear event-stream scrollback (visual only, no DB effect) |
| `q` | Quit (confirm if unsent intervention typed) |

#### Command mode (after `:`)

Free-form text. On `Enter`:

- `:reject H_07 reason text` → reject intervention
- `:halt reason text` → halt
- `:pin dataset metric value` → pin metric
- `:note free text` → write a note event into `cockpit_events(kind="note")` for posterity
- `:` (empty + Enter) → no-op, exits Command mode

#### Filter mode (after `/`)

Substring match against the visible columns of the focused pane. Live-narrowing as you type. `Enter` keeps the filter; `Esc` clears it. The active filter shows in the pane title: `┌─ 1 Hypothesis Tree (filter: dropout) ─┐`.

### 4.4 Color palette (GitHub Dark, defined in `cockpit.tcss`)

| Role | Hex | Usage |
|---|---|---|
| `--bg` | `#0d1117` | App background (also: terminal default if user has it set) |
| `--fg` | `#c9d1d9` | Default text |
| `--muted` | `#6e7681` | Inactive timestamps, parent breadcrumbs, refuted nodes |
| `--accent` | `#58a6ff` | Focused row, focused pane border, selected tab |
| `--success` | `#3fb950` | Verified claims, "approved" interventions, evidence-supports edges |
| `--danger` | `#f85149` | Refuted nodes, halt action, failures with high seen_count |
| `--warning` | `#d29922` | Pending interventions (queued but not delivered), contradictions |
| `--border` | `#21262d` | All pane borders (Unicode `─│┌┐└┘`) |
| `--cursor-bg` | `#1f6feb` | Selected row background in DataTables |

**Node-kind colors** (used in tree and detail header):
- `question`: cyan `#79c0ff`
- `hypothesis`: blue `#58a6ff` (active) / red strikethrough `#f85149` (refuted) / gray `#6e7681` (archived)
- `experiment`: amber `#d29922`
- `evidence`: green `#3fb950` (supports) / red `#f85149` (refutes)
- `conclusion`: magenta `#bc8cff`

**Typography rules**:
- Pane titles: bold, accent color when focused, muted when not
- Hypothesis text: regular weight, kind-color prefix tag (`H_07`)
- Refuted nodes: strikethrough + muted (only visible when `s` toggled on)
- Event-stream timestamps: muted gray, fixed-width
- Numbers (counts, IDs): tabular figures via `Text("12", style="bold")`

### 4.5 Pane-by-pane spec

#### Pane 1 — Hypothesis Tree (`HypothesisTreePane`)

- Widget: `textual.widgets.Tree`
- Data source: `mem_nodes` + `mem_edges` (only `relation='parent_of'` edges build the tree spine; other relations shown in detail pane)
- Root nodes: all `question` kind with no incoming `parent_of` edge
- Lazy-loaded children (don't expand all on mount; expand on `l` or `Enter`)
- Auto-scroll to newly-arrived node when a `graph_delta` event lands (with a 200ms accent-color flash via `tree.styles.animate`)
- Cross-edges (e.g., `contradicts`, `supports`) are **not** drawn here; they appear as a "Cross-edges:" line in pane 2

#### Pane 2 — Node Detail (`NodeDetailPane`)

- Widget: `Static` (rich-text rendered)
- Updates on `Tree.NodeSelected` from pane 1
- Layout (top-to-bottom):
  1. Header line: `<id>  <kind>  state: <state>` (kind-colored)
  2. Separator
  3. Full text of node (wrapped, no truncation)
  4. Blank line
  5. `Parents:` line (comma-separated IDs, clickable via `gP` to jump)
  6. `Children:` line (same)
  7. `Cross-edges:` line — `⇄ H_08 (contradicts)` style, one per line if multiple
  8. `Evidence:` summary count
  9. `Created:` timestamp, `Created by:` agent name
- If no node is selected: shows a one-line hint "Select a hypothesis with j/k or click."

#### Pane 3 — Event Stream (`EventStreamPane`)

- Widget: `RichLog(max_lines=2000, auto_scroll=True, wrap=False)`
- Tailed by the `events_worker` (see §4.6)
- Each line format: `HH:MM:SS  <kind>  <one-line summary>`
  - `graph_delta`: `graph_delta H_09 hypothesis init-scale matters`
  - `failure_added`: `failure_added f_7 fit_on_concat (signature: f8a3b2)`
  - `turn_end`: `turn_end Δ +2/−0/+1f` (nodes added / refuted / failures added)
  - `intervention`: `intervention reject H_07 by user`
  - `note`: `note <text>` (user-written)
- Color: kind name in accent, summary in default fg, timestamp muted
- `t` toggles to relative timestamps (`-2m 14s ago`)
- Filterable with `/`

#### Pane 4 — Right-tabbed pane (`RightTabsPane`)

A `TabbedContent` widget with three tabs. `f` cycles through them.

- **Tab "Failures"** (`DataTable`)
  - Columns: `#`, `trigger`, `symptom`, `seen`
  - Sort default: `seen DESC` then `last_seen DESC`
  - Row select → fills detail panel with full failure record (overrides node detail temporarily; press `Esc` to restore)
- **Tab "Claims"** (`DataTable`)
  - Source: `ver_metric_pins JOIN ver_provenance`
  - Columns: `metric`, `value`, `dataset`, `verified`, `seeds`
  - "verified" column shows ✓ (success color) or ✗ (danger color) based on whether `seed_perturb` has run
  - "seeds" shows N/3 progress for in-flight verification
- **Tab "Literature"** (`DataTable`)
  - Source: `mem_lit_compressed`
  - Columns: `paper_id`, `title (truncated)`, `year`, `task`, `score`
  - `Enter` → opens compressed-summary modal showing all structured fields

### 4.6 Live-update mechanism (`events_worker`)

```python
class CockpitApp(App):
    last_event_id = reactive(0)

    @work(exclusive=True)
    async def events_worker(self) -> None:
        while True:
            new_rows = await asyncio.to_thread(
                self._fetch_new_events, self.last_event_id
            )
            if new_rows:
                for row in new_rows:
                    self.dispatch_event(row)
                self.last_event_id = new_rows[-1]["id"]
            await asyncio.sleep(1.0)

    def dispatch_event(self, row):
        # write to event-stream pane
        self.query_one(EventStreamPane).post(row)
        # selectively refresh affected panes
        if row["kind"] == "graph_delta":
            self.query_one(HypothesisTreePane).refresh_node(row["payload"]["node_id"])
        elif row["kind"] == "failure_added":
            self.query_one(RightTabsPane).refresh_failures()
        elif row["kind"] == "turn_end":
            self.query_one(EventStreamPane).write_separator(row["payload"])
```

- Single 1-second poll; cost = one indexed `SELECT id > ?` per second. Negligible.
- `asyncio.to_thread` keeps SQLite calls off the event loop so UI never stalls.
- `last_event_id` is reactive, so a watcher updates the header counter automatically.
- When the user presses `R`, the worker is bumped via an `asyncio.Event` and immediately re-polls.

### 4.7 Modals

| Modal | Trigger | Behavior |
|---|---|---|
| **HelpScreen** | `?` | Read-only overlay listing all bindings, grouped by section. Dismiss: any key. |
| **ConfirmModal** | `m`, `H`, quit-with-pending | "Are you sure? (y/n)". Returns bool. |
| **TextInputModal** | `r`, `c`, `:` | Single-line input with placeholder per kind. Returns string or None. |
| **PinMetricModal** | `p` | Three-field form: dataset, metric, value. Returns dict or None. Validates value is a float. |
| **NodeDrillModal** | `Enter` on evidence in detail panel | Shows full evidence text + provenance hash + linked metric pins. Dismiss: `Esc`. |

All modals respect the same color palette and use `ModalScreen[T]` with typed return values.

### 4.8 Aesthetic / ergonomic notes (lessons from k9s, lazygit, btop)

- **Borders only ASCII / box-drawing range** (U+2500–U+257F). Avoid CJK box characters and emoji glyphs in chrome — Windows Terminal still misaligns them as of April 2026 (Textual issue #6025).
- **Footer is the single source of truth for keybindings.** Never put a keybinding in a tooltip or hover state. The Footer auto-renders from `BINDINGS` so help and behavior cannot drift apart.
- **Focused-pane border highlight is bold + accent color, unfocused is muted.** This is the only chrome change between focused/unfocused — no popup, no flashing.
- **Animations are 150–250 ms accent-color flashes only.** Long animations annoy in long sessions.
- **Refuted nodes hidden by default**, but `s` toggles them visible (strikethrough + muted). Lazygit-style "show all" toggle.
- **No truncation in detail pane.** Wrap text. Truncation only in tables (with `…` and tooltip on hover via Textual's tooltip system).
- **Header row is one line and stays put.** Format: `app_name  state.db: <counts>  HH:MM`.
- **Footer row is one line and stays put.** Format: `key  action · key  action · …` — top 6 most-frequent only; full list via `?`.
- **Empty-state messages.** Each pane shows a one-line hint when empty (e.g., "No hypotheses yet. Trigger a research session in Claude Code.") — no blank pane.
- **Color blindness fallback.** All semantic colors are paired with a glyph: ✓ ✗ ⇄ ▾ ▸ — never color-only.
- **Quit confirmation only when there's unsent input** (typed but un-Enter'd command, or open modal). Otherwise `q` quits immediately.

### 4.9 File layout (TUI module)

```
src/cockpit/
├── __init__.py
├── tui.py                    # entry point: python -m cockpit.tui
├── app.py                    # CockpitApp(App) — root widget tree, BINDINGS, workers
├── panes/
│   ├── __init__.py
│   ├── tree_pane.py          # HypothesisTreePane(Tree)
│   ├── detail_pane.py        # NodeDetailPane(Static)
│   ├── events_pane.py        # EventStreamPane(RichLog)
│   └── tabs_pane.py          # RightTabsPane(TabbedContent) + 3 inner tables
├── modals/
│   ├── __init__.py
│   ├── help.py               # HelpScreen
│   ├── confirm.py            # ConfirmModal
│   ├── text_input.py         # TextInputModal
│   └── pin_metric.py         # PinMetricModal
├── data.py                   # _fetch_new_events, _fetch_graph, _fetch_failures, _fetch_claims, _fetch_literature, _write_intervention
├── theme/
│   └── cockpit.tcss          # the full color + layout stylesheet
└── mcp_server.py             # cockpit-MCP (stdio) — push_graph_delta + write_intervention tools
```

`data.py` is the only place that touches `runtime.connect_sqlite()` — keeps SQL out of widgets.

---

## 5. Backend Changes (kill FastAPI, cockpit-MCP → stdio)

### 5.1 Files to delete

```
src/cockpit/server.py                      # FastAPI app + uvicorn entry — DELETE
src/cockpit/frontend/                      # entire React subtree — DELETE
  ├── src/App.tsx
  ├── src/components/HypothesisGraph.tsx
  ├── src/components/InterventionPanel.tsx
  ├── src/components/VerificationTable.tsx
  ├── src/hooks/useWebSocket.ts
  ├── package.json, vite.config.ts, tailwind.config.ts, tsconfig.json
  └── node_modules/                        # also delete (gitignored anyway)
```

### 5.2 Files to add

`src/cockpit/mcp_server.py` — replaces the FastMCP HTTP sub-app from `server.py`:

```python
from fastmcp import FastMCP
from claudescientist.runtime import connect_sqlite, state_db_path

mcp = FastMCP("cockpit")

@mcp.tool
def push_graph_delta(node_id: str, kind: str, text: str) -> dict:
    """Called by main Claude when a new node is created."""
    with connect_sqlite(state_db_path()) as con:
        con.execute(
            "INSERT INTO cockpit_events(kind, payload) VALUES(?, ?)",
            ("graph_delta", json.dumps({"node_id": node_id, "kind": kind, "text": text})),
        )
    return {"ok": True}

@mcp.tool
def queue_intervention(kind: str, target: str | None, payload: str) -> dict:
    """Programmatic equivalent of POST /intervene — useful for scripts."""
    # ... insert into cockpit_interventions ...
    return {"ok": True}

if __name__ == "__main__":
    mcp.run()  # stdio
```

### 5.3 settings.json diff

```diff
   "cockpit": {
-    "transport": {
-      "type": "http",
-      "url": "http://127.0.0.1:7777/mcp"
-    }
+    "command": "uv",
+    "args": ["run", "python", "-m", "cockpit.mcp_server"]
   },
```

### 5.4 pyproject.toml diff

Remove unused deps (FastAPI, uvicorn, websockets if pinned), add Textual:

```diff
-fastapi>=0.115
-uvicorn>=0.34
+textual>=8.2.3
```

`fastmcp` stays — used by `cockpit/mcp_server.py`. SQLite is stdlib.

### 5.5 Tests to delete / replace

- Delete: anything in `tests/cockpit/test_server.py`, `tests/cockpit/test_websocket.py`
- Add:
  - `tests/cockpit/test_data.py` — data-layer SQL, no Textual dependency
  - `tests/cockpit/test_mcp_server.py` — stdio MCP behaves like memory/verify (use `fastmcp.client` like the v0.1 MCP tests)
  - `tests/cockpit/test_app_smoke.py` — uses Textual's `App.run_test()` async harness to spin up the app, simulate keystrokes (`pilot.press("j", "y")`), assert DB state

---

## 6. seed_perturb + baseline_fairness in verify-mcp

### 6.1 New tools in `src/verify_mcp/impl.py`

```python
@mcp.tool
def seed_perturb(
    script_path: str,
    seed_arg: str = "--seed",
    seeds: list[int] | None = None,
    metric_pattern: str = r"test[_ ]acc(uracy)?[: =]+([\d.]+)",
    timeout_sec: int = 600,
) -> dict:
    """Run script with N seeds, return mean/std of extracted metric."""
    seeds = seeds or [0, 1, 2]
    values = []
    for s in seeds:
        result = subprocess.run(
            ["uv", "run", "python", script_path, seed_arg, str(s)],
            capture_output=True, text=True, timeout=timeout_sec,
        )
        m = re.search(metric_pattern, result.stdout)
        if not m:
            return {"ok": False, "error": f"metric not found for seed {s}"}
        values.append(float(m.group(2)))
    return {
        "ok": True,
        "seeds": seeds,
        "values": values,
        "mean": statistics.mean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "verdict": "stable" if statistics.stdev(values) < 0.01 else "unstable",
    }

@mcp.tool
def baseline_fairness(
    proposed_log: str,
    baseline_log: str,
    threshold_ratio: float = 3.0,
) -> dict:
    """Compare hyperparameter budgets across two run logs."""
    p = _extract_budget(proposed_log)  # {"epochs": int, "lr_trials": int, "param_count": int}
    b = _extract_budget(baseline_log)
    ratios = {k: p[k] / max(b[k], 1) for k in p}
    unfair = {k: r for k, r in ratios.items() if r > threshold_ratio}
    return {
        "ok": True,
        "proposed": p,
        "baseline": b,
        "ratios": ratios,
        "verdict": "fair" if not unfair else "unfair",
        "unfair_axes": unfair,
    }
```

Helpers (`_extract_budget`) live in `src/verify_mcp/budget.py` (new file). Regex-based, conservative. If parsing fails, return `None` for unknown axes (caller decides).

### 6.2 New table: `ver_seed_runs`

```sql
CREATE TABLE ver_seed_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  script_path TEXT NOT NULL,
  seeds_json TEXT NOT NULL,        -- '[0,1,2]'
  values_json TEXT NOT NULL,       -- '[0.91, 0.89, 0.92]'
  mean_value REAL NOT NULL,
  std_value REAL NOT NULL,
  verdict TEXT NOT NULL,           -- 'stable' / 'unstable'
  metric_pin_id INTEGER,           -- FK ver_metric_pins (nullable)
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (metric_pin_id) REFERENCES ver_metric_pins(pin_id)
);
```

When `seed_perturb` runs against a script tied to a pinned metric, it backfills the pin's verification status. The TUI's "Claims" tab reads this join.

### 6.3 Tests

- `tests/verify_mcp/test_seed_perturb.py` — fixtures: a deterministic script (returns same number) and a noisy one (random per-seed). Assert verdicts.
- `tests/verify_mcp/test_baseline_fairness.py` — synthetic logs with known budget ratios.

---

## 7. Research-taste skill + SOP refinement

### 7.1 New skill: `.claude/skills/elo-select.md`

A skill that, given K candidate hypotheses, runs ⌈K log K⌉ pairwise comparisons via the same Claude session (no subagent spawn — single tool call back to a `judge_hypotheses(a, b)` MCP tool in memory-mcp), assigns Elo, returns top-2 with scores and reasoning.

Triggers when:
- The researcher subagent has just emitted ≥ 3 hypothesis nodes in one turn
- OR the user runs `/elo-select` explicitly

### 7.2 New tool in memory-mcp: `judge_hypotheses`

```python
@mcp.tool
def judge_hypotheses(
    hypothesis_a_id: str,
    hypothesis_b_id: str,
    criteria: list[str] = None,
) -> dict:
    """Returns winner_id, reason. Criteria default: novelty, feasibility, falsifiability."""
    # Fetch both nodes' text
    # Build a prompt for the SAME model (no spawn) — return the prompt for the
    # caller (Claude) to evaluate inline, then call `record_judgement`.
```

Two-step pattern: `judge_hypotheses` returns the prompt; Claude evaluates; Claude calls `record_judgement(a, b, winner, reason)`. Avoids subagent spawn cost and stays inside one model context.

### 7.3 Elo storage: extend `mem_nodes`

```sql
ALTER TABLE mem_nodes ADD COLUMN elo_score REAL DEFAULT 1500.0;
```

Plus a tiny ledger:

```sql
CREATE TABLE mem_judgements (
  judgement_id INTEGER PRIMARY KEY AUTOINCREMENT,
  a_node_id TEXT NOT NULL,
  b_node_id TEXT NOT NULL,
  winner_node_id TEXT NOT NULL,
  reason TEXT,
  k_factor REAL DEFAULT 32.0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (a_node_id) REFERENCES mem_nodes(node_id),
  FOREIGN KEY (b_node_id) REFERENCES mem_nodes(node_id),
  FOREIGN KEY (winner_node_id) REFERENCES mem_nodes(node_id)
);
```

`record_judgement` updates Elo on both nodes per standard formula (K=32).

### 7.4 SOP changes

- `research-sop`: after researcher proposes K hypotheses, if K ≥ 3, invoke elo-select before handing the top-2 to engineer.
- `writeup-sop`: cite Elo score next to each hypothesis discussed.

### 7.5 Tests

- `tests/memory_mcp/test_elo.py` — synthetic 5-hypothesis tournament, assert ranking is consistent with synthetic ground truth.

---

## 8. Held-out budget enforcement

### 8.1 New CLI tool: `uv run python -m claudescientist.heldout register <name> <path>`

Moves `<path>` to `~/.research-agent/heldout/<name>/`, computes SHA-256 of all files, writes `manifest.json`. The original location gets a `.heldout-pointer` file with the new path. The leakage_guard hook reads `.heldout-pointer` files and **always blocks Read of the data they point to** — only `query_heldout` can access it.

### 8.2 New table & MCP tool

```sql
CREATE TABLE ver_heldout_budgets (
  dataset TEXT PRIMARY KEY,
  manifest_sha256 TEXT NOT NULL,
  budget_total INTEGER NOT NULL DEFAULT 5,
  budget_used INTEGER NOT NULL DEFAULT 0,
  registered_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ver_heldout_queries (
  query_id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset TEXT NOT NULL,
  model_path TEXT NOT NULL,
  metric_value REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

```python
@mcp.tool
def query_heldout(dataset: str, model_path: str, batch_size: int = 1) -> dict:
    """Run model_path on heldout dataset; decrement budget."""
    # 1. Verify manifest hash matches stored
    # 2. Check budget_used < budget_total
    # 3. Subprocess: uv run python <model_path> --dataset <heldout_path>
    # 4. Parse single metric from stdout
    # 5. Insert ver_heldout_queries row, increment budget_used
    # 6. Return metric + remaining budget
```

### 8.3 Hook integration

`leakage_guard.py` adds a check: if the file being Written/Edited contains a path that resolves to `~/.research-agent/heldout/<name>/`, block with `permissionDecision: "deny"` and reason "held-out dataset access only via query_heldout".

### 8.4 Tests

- `tests/verify_mcp/test_heldout.py`:
  - register dataset, query 5 times, 6th call returns `{"ok": False, "error": "budget_exceeded"}`
  - tamper with manifest, query returns `{"ok": False, "error": "manifest_drift"}`
- `tests/hooks/test_leakage_guard_heldout.py`:
  - Write event targeting heldout path → blocked

---

## 9. Project Layout (v0.2 diff)

```
src/
├── claudescientist/
│   ├── runtime.py                    # unchanged
│   └── heldout_cli.py                # NEW
├── memory_mcp/
│   ├── impl.py                       # +judge_hypotheses, +record_judgement
│   ├── schema.sql                    # +mem_judgements, +elo_score column
│   └── ...
├── verify_mcp/
│   ├── impl.py                       # +seed_perturb, +baseline_fairness, +query_heldout
│   ├── budget.py                     # NEW (log parser)
│   ├── schema.sql                    # +ver_seed_runs, +ver_heldout_budgets, +ver_heldout_queries
│   └── ...
└── cockpit/
    ├── tui.py                        # NEW entry
    ├── app.py                        # NEW
    ├── data.py                       # NEW (was: server.py SQL fragments)
    ├── mcp_server.py                 # NEW (replaces server.py's MCP sub-app)
    ├── theme/cockpit.tcss            # NEW
    ├── panes/                        # NEW (4 files)
    ├── modals/                       # NEW (4 files)
    ├── server.py                     # DELETE
    └── frontend/                     # DELETE entire tree

.claude/
├── settings.json                     # cockpit MCP entry: HTTP → stdio
├── skills/
│   └── elo-select.md                 # NEW
└── ...

docs/
└── plan-v0.2.md                      # NEW (this document, copied as Step 0)

tests/
├── cockpit/
│   ├── test_data.py                  # NEW
│   ├── test_mcp_server.py            # NEW
│   ├── test_app_smoke.py             # NEW
│   ├── test_server.py                # DELETE
│   └── test_websocket.py             # DELETE (if exists)
├── memory_mcp/test_elo.py            # NEW
├── verify_mcp/test_seed_perturb.py   # NEW
├── verify_mcp/test_baseline_fairness.py  # NEW
├── verify_mcp/test_heldout.py        # NEW
└── hooks/test_leakage_guard_heldout.py   # NEW
```

---

## 10. v0.2 Executable Plan (Phases 7–10)

(v0.1 used Phases 0–6.)

### Phase 7 — TUI scaffold + read-only parity (3 days)

**Goal**: TUI launches, reads SQLite, shows graph + failures + events live. No interventions yet.

1. Add `textual>=8.2.3` to `pyproject.toml`. `uv sync`.
2. Create `src/cockpit/tui.py`, `app.py`, `data.py`, `theme/cockpit.tcss`, all 4 panes (read-only).
3. Wire the 1-second `events_worker`. Verify event-stream pane updates within 1s of an MCP write.
4. Verification: open TUI, run `mcp__memory__propose_hypothesis` from a test session, assert tree updates and events scroll in.

### Phase 8 — TUI interventions + modals + cockpit-mcp stdio (3 days)

**Goal**: Full feature parity with v0.1 WebUI. WebUI files deletable.

1. Implement all modals (help, confirm, text-input, pin-metric).
2. Wire all action keybindings (`y/n/r/c/m/p/H/:`); writes go through `data.py` → `cockpit_interventions`.
3. Rewrite `src/cockpit/mcp_server.py` as stdio.
4. Update `.claude/settings.json` cockpit entry from HTTP to stdio.
5. Delete `src/cockpit/server.py` and `src/cockpit/frontend/`.
6. Remove FastAPI/uvicorn from `pyproject.toml`. `uv sync`.
7. Verification: full v0.1 smoke test (§11) but with TUI instead of browser. End-to-end intervention round-trip works.

### Phase 9 — verify-mcp seed_perturb + baseline_fairness (4 days)

**Goal**: Tools shipped, schema migrated, TUI Claims tab shows verification verdict.

1. Implement `seed_perturb` and `baseline_fairness` in `src/verify_mcp/impl.py`. Tests pass.
2. Add `ver_seed_runs` table via `apply_schema_migration`.
3. Update TUI Claims tab data-source SQL to JOIN `ver_seed_runs` and show ✓/✗.
4. Add a verifier-subagent SOP step: after `pin_metric`, automatically suggest `seed_perturb` if not yet run.
5. Verification: run a deterministic + a noisy script, see "stable"/"unstable" verdicts in Claims tab.

### Phase 10 — research-taste (Elo) + held-out budget (5 days)

**Goal**: Hypothesis ranking via Elo; held-out access fully gated.

1. Add `mem_judgements` table + `elo_score` column via migration.
2. Implement `judge_hypotheses` + `record_judgement` in memory-mcp.
3. Write `.claude/skills/elo-select.md`.
4. Update `research-sop` to invoke elo-select when K ≥ 3.
5. Implement `claudescientist.heldout_cli` (register/list/inspect).
6. Add `ver_heldout_budgets` + `ver_heldout_queries` tables.
7. Implement `query_heldout` MCP tool.
8. Extend `leakage_guard.py` to block Read/Write/Edit of heldout paths.
9. Tests pass.
10. Verification: register a synthetic dataset, propose 5 hypotheses, see Elo ranks in TUI, confirm Read of heldout dataset is blocked.

### Phase 0 of v0.2 (do this before Phase 7)

Copy this plan file to `D:\aiscientist\claudescientist\docs\plan-v0.2.md` (create `docs/` if it doesn't exist). This makes the plan part of the repo and CI can lint-check that plan-claimed files exist.

---

## 11. Verification Plan

### v0.2 end-to-end smoke test

```powershell
# Terminal A:
cd D:\aiscientist\claudescientist
claude   # start Claude Code

# Terminal B:
cd D:\aiscientist\claudescientist
uv run python -m cockpit.tui
```

In Terminal A:

1. `/research-sop investigate whether dropout rate affects ViT scaling`
   → expect (in TUI Terminal B): tree fills with question + 5 hypotheses within 5s; "graph_delta" lines stream into events pane; elo-select skill fires automatically (≥3 hypotheses); top-2 hypotheses' Elo scores visible in detail pane.
2. In Terminal B: focus tree (`1`), navigate to weakest hypothesis (`j` × N), press `n` (reject)
   → expect: "intervention" event appears immediately; on Claude's next turn in Terminal A, the rejection is injected as `additionalContext` and Claude drops that hypothesis.
3. In Terminal A: `@engineer implement the remaining hypothesis as a MNIST-proxy training script with --seed argument`
   → expect: clean code passes leakage_guard; script saved.
4. In Terminal A: `mcp__verify__seed_perturb script_path=mnist_proxy.py seeds=[0,1,2]`
   → expect: TUI Claims tab shows the metric with ✓ verified + mean/std.
5. In Terminal A: `uv run python -m claudescientist.heldout register mnist-test ./data/mnist-test/`
   → expect: directory moves; pointer left behind.
6. In Terminal A: ask Claude to read `./data/mnist-test/labels.csv`
   → expect: leakage_guard blocks; suggests `query_heldout` instead.
7. End session, restart, restart TUI
   → expect: graph state, Elo scores, seed-run history, budget counters all persist.

### Regression tests (added in v0.2)

- `tests/cockpit/test_data.py` — pure SQL layer
- `tests/cockpit/test_mcp_server.py` — stdio MCP echoes v0.1 behavior
- `tests/cockpit/test_app_smoke.py` — `App.run_test()` + `pilot.press` keystrokes
- `tests/memory_mcp/test_elo.py` — Elo update math, judgement ledger
- `tests/verify_mcp/test_seed_perturb.py` — stable + unstable fixtures
- `tests/verify_mcp/test_baseline_fairness.py` — fair + unfair budget logs
- `tests/verify_mcp/test_heldout.py` — budget exhaust + manifest drift
- `tests/hooks/test_leakage_guard_heldout.py` — block on heldout-pointer

Target: all v0.1 tests still pass + 7 new test files green.

### Manual TUI ergonomics check (~20 min)

After Phase 8, sit with the TUI for 20 minutes during real use:

- Can you find any binding without opening `?`
- Does any pane border misalign in Windows Terminal at 120×40
- Does any color have insufficient contrast on your monitor
- Is the 1s event-pane lag noticeable (it shouldn't be)
- Does `q` work without hitting an unconfirmed quit modal accidentally

Record findings in `docs/plan-v0.2.md` Appendix as "ergonomics review" before declaring v0.2 done.

---

## 12. Rollback / Migration Notes

- The TUI and the (deleted) WebUI both write the same `cockpit_interventions` schema. If the user wants to revert to WebUI mid-Phase 8, `git revert` of the deletion commit + `npm install` in `frontend/` restores it. No DB migration needed in either direction.
- `apply_schema_migration` (already in `runtime.py`) handles all 4 new schema changes idempotently. Re-running v0.2 setup on an existing v0.1 DB is safe.
- The cockpit-MCP transport change (HTTP → stdio) is the only one that requires Claude Code to be restarted for it to take effect (settings.json reload).

---

## 13. Open Items (decide during execution, not blockers)

- **Textual version pin**: 8.2.3 is current; pin loosely to `>=8.2,<9.0` to allow patches.
- **Pairwise judge K-factor**: default 32 is borrowed from chess; if rankings feel too noisy, drop to 16 in Phase 10 verification.
- **Held-out budget default of 5**: gut feeling, not measured. Adjustable per-dataset on `register`.
- **TUI dark/light theme toggle**: deferred to v0.3 unless user requests it. Dark only for v0.2.

---

## 14. References

- Textual docs: https://textual.textualize.io
- k9s keybinding cheatsheet: https://k9scli.io/topics/commands/
- lazygit keybinding philosophy: https://github.com/jesseduffield/lazygit/blob/master/docs/keybindings/Keybindings_en.md
- Elo rating formula: https://en.wikipedia.org/wiki/Elo_rating_system
- (carry-over from v0.1) Claude Code hooks, fastmcp, uv, MCP protocol
