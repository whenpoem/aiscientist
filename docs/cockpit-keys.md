# Cockpit key reference

> 中文版本：[cockpit-keys.zh-CN.md](cockpit-keys.zh-CN.md)
> The canonical key-by-scope map for the Textual cockpit. Anything in
> the cockpit's `BINDINGS` list at app or pane level should appear
> here. New bindings without a corresponding entry are a documentation
> drift bug.

Keys fall into one of four scopes. The scope determines where you have
to be focused for the key to fire.

## Global (priority bindings)

These fire from anywhere — focused pane, focused modal, focused
DataTable, all the same. They take precedence over the focused widget's
own bindings.

| Key | Action |
|---|---|
| `L` | Toggle language (en ↔ zh) |
| `T` | Cycle theme |
| `F` | Toggle single-pane focus mode |
| `H` | Halt the running agent turn |
| `R` | Force-refresh the current state |
| `N` | Jump to the next tab group (Cross → Empirical → Proof) |
| `P` | Toggle phase strip visibility (v5.0) |
| `M` | Mute / unmute activity-pane animations (v5.0) |
| `a` / `A` | Show / hide the audit log view (v5.0) |
| `b` | Toggle bookmark on the selected node (v5.1) |
| `B` | Open the bookmarks navigator modal (v5.1) |
| `u` | Undo the most recent intervention (only if undelivered) |
| `<` / `>` | Nudge wide-layout tree column narrower / wider |
| `q` | Quit the app (pops the current Screen first if one is open) |
| `Esc` | Cancel the current context (close modal, exit filter, …) |
| `Ctrl+L` | Clear the audit log (formerly the events pane) |
| `Ctrl+P` | Open the command palette |

A priority-binding helper inside the App ensures that capital-letter
priority keys yield to any focused `Input` widget — typing literal `L`
inside a modal field still types `L` rather than toggling language.
The helper covers `L`, `T`, `F`, `H`, `R`, `N`, `u`, `<`, `>`, the
v5.0 additions `P`, `M`, `a`, `A`, and the v5.1 additions `b`, `B`.

## Selection actions

These take the *currently selected* node (tree cursor) as their target,
regardless of which pane has focus. They are App-level non-priority
bindings.

| Key | Action |
|---|---|
| `y` | Approve the selected node |
| `n` | Reject the selected node |
| `r` | Redirect the selected node |
| `c` | Constrain the selected node |
| `m` | Mark the selected node refuted |
| `p` | Pin a metric on the selected node |

## Movement

Movement keys work in every focusable pane. Their meaning depends on
the focused widget (move tree cursor, scroll event log, advance tab
row), but the bindings themselves are App-level.

| Key | Action |
|---|---|
| `j` / `k` | Move down / up |
| `h` / `l` | Collapse / expand or move left / right |
| `g` / `G` | Jump to top / bottom |
| `1` – `4` | Focus tree / detail / activity / tabs pane (`3` was `events` pre-v5; the rename is healed automatically on settings load) |
| `Tab` / `Shift+Tab` | Cycle focus to next / previous pane |
| `Enter` | Drill into the selected item |
| `f` | Cycle to the next tab inside the current group |

## Pane-scoped

These only fire when the named pane has focus. Pressing them from
elsewhere is intentionally a no-op — the cockpit no longer fights for
priority on these because the action only makes sense from inside the
pane.

| Pane | Key | Action |
|---|---|---|
| Audit log (was Events) | `w` | Toggle soft-wrap on event payloads — the binding travels with the widget; open/focus the audit log with `a` / `A` first |
| Audit log (was Events) | `t` | Toggle relative vs absolute timestamp rendering |
| Tree | `i` | Toggle compact tree labels (show / hide BT + Elo) |

## Modal / filter input

Inside a modal or the filter / command-line input, only `Escape`,
`Enter`, and the field-cycling keys (`Tab`, `Shift+Tab`) are
interpreted as commands. Every other key types into the input.

## Footer behavior

The Textual `Footer` reads bindings from the focused widget upward.
When the events pane is focused you should see `w Wrap` in the footer;
when the tree pane is focused you should see `i Tree info` instead.
Global bindings (`L`, `T`, `F`, …) appear regardless of focus.

## Adding a new binding

Decide its scope first:

- **Global** — only when the action makes sense no matter where the
  user is looking. The bar for global priority bindings is high; the
  helper that forwards literal letters into `Input` widgets has to
  cover every priority letter.
- **Selection** — works on the tree's selected node. Add it to the
  App's `BINDINGS` non-priority list and document above.
- **Movement** — same caveats as selection.
- **Pane-scoped** — define `BINDINGS = [...]` on the pane class, plus
  an `action_<name>` method on that pane. The pane class' bindings
  ship in its module, not in `app.py`.

If you add a new key that's not on this page, the doc has drifted.
Add the row before merging.
