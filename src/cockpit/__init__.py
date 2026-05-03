"""cockpit - Textual TUI dashboard plus a stdio MCP bridge.

The user-facing observation surface for ClaudeScientist. Reads SQLite via
short-poll workers and writes user interventions back into
``cockpit_interventions``. The ``mcp_server`` exposes a thin set of
push-side tools (graph delta, intervention queue, free-form note) so
Claude can mark events the cockpit should highlight.

Public surface
--------------
CockpitApp                 The Textual App; mounted by ``main()``.
main()                     CLI entry point: ``python -m cockpit.tui``.
render_snapshot()          Headless render used by ``--once`` mode + tests.
mcp                        FastMCP instance (push_graph_delta etc.).

Owned tables (cockpit_*)
------------------------
cockpit_events             Append-only event stream (memory + verify + hooks
                           write here; cockpit polls). Schema also touched
                           by runtime.emit_cockpit_event so it works even
                           before the cockpit has booted.
cockpit_interventions      User actions queued by the TUI; drained by the
                           ``intervention_pump`` hook on the next
                           UserPromptSubmit / Stop event.

Critical invariants
-------------------
- ``cockpit/db.ensure()`` calls ``runtime.bootstrap_all()`` so every
  registered MCP schema is in place before cockpit reads cross-module
  tables. Do NOT directly import bootstrap from memory_mcp / verify_mcp -
  that re-introduces a layering perforation.
- All user-visible text routes through ``cockpit.i18n`` so English and
  Chinese modes stay aligned.
- ``cockpit/data.py`` may lazily import ``memory_mcp.impl`` and
  ``verify_mcp.impl`` for write-back operations (refute, pin) - this is a
  deliberate plugin-style call, not a perforation; the imports are inside
  function bodies and only at call time.
- The TUI is terminal-first. Do not introduce a browser frontend, Vite,
  or uvicorn dependency.

Where things live
-----------------
Textual App + key bindings:  app.py
TUI entry point:             tui.py
Headless / once-mode render: app.render_snapshot
Pane widgets:                panes/
Modal screens:               modals/
Theme / CSS:                 theme/cockpit.tcss
SQLite + bootstrap:          db.py (ensure() + connect())
Data access layer:           data.py (read graph / events / claims; write
                             interventions; lazy plugin imports)
i18n labels:                 i18n.py
MCP bridge:                  mcp_server.py (push_graph_delta, queue_intervention,
                             record_note)

Do NOT
------
- Hard-code labels inside widgets; route through ``cockpit.i18n``.
- Import memory_mcp or verify_mcp at module level. The lazy imports in
  data.py are the only allowed exception.
- Mutate ``mem_*`` or ``ver_*`` tables directly. Use the lazy plugin
  imports of memory_mcp.impl / verify_mcp.impl from data.py.
- Add a non-stdio MCP transport. The cockpit MCP runs over stdio, like
  memory and verify.
"""

from __future__ import annotations

from .app import CockpitApp, main, render_snapshot
from .mcp_server import mcp

__all__ = ["CockpitApp", "main", "mcp", "render_snapshot"]
