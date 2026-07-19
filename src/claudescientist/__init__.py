"""claudescientist - Foundation runtime layer for ClaudeScientist.

Owns project-wide path resolution, the SQLite connection helper, schema
migration bookkeeping, the cockpit-event emit primitive, the project-level
metric-recognition regexes, and the component bootstrap registry. Every
business module (memory_mcp, verify_mcp, cockpit) depends on this; this
module must not depend on any of them.

Public surface
--------------
runtime.state_db_path()           Resolve the shared SQLite file path.
runtime.heldout_root()            Resolve the sequestered-dataset root.
runtime.connect_sqlite()          WAL-mode connection with row factory.
runtime.connect_existing_sqlite() Hook-safe existing-DB connection helper.
runtime.apply_schema_migration()  Per-component schema apply + bookkeeping.
runtime.emit_cockpit_event()      Append a row to cockpit_events in-tx.
runtime.METRIC_RE / NUMBER_RE     Project-wide numeric-claim recognition.
runtime.extract_metric_tokens()   Pull labelled metric values from text.
runtime.bootstrap_all()           Bootstrap every registered component.
heldout.compute_manifest()        Hash a directory into a content manifest.
heldout.load_manifest()           Read a previously-written manifest.
heldout.write_manifest()          Persist a manifest next to the dataset.
heldout.dataset_root()            Resolve a named dataset's root path.
heldout.main()                    CLI entry point (lazy bridge to verify_mcp).

Owned tables
------------
ra_migrations         Per-component schema version + apply status (created
                      on demand by apply_schema_migration).
cockpit_events        Append-only event stream (created on demand by
                      emit_cockpit_event); cross-module signals go here.

Critical invariants
-------------------
- runtime never imports memory_mcp, verify_mcp, or cockpit at module level.
  ``bootstrap_all`` uses ``importlib.import_module`` so this stays true.
- ``state_db_path()`` is the only legitimate way to find the SQLite file.
  Do not duplicate path resolution.
- ``METRIC_RE`` / ``extract_metric_tokens`` are project-wide; verify_mcp.
  provenance and the hooks both consume them through this module.
- ``KNOWN_BOOTSTRAP_COMPONENTS`` is the single registry of "modules that
  own a SQLite schema". Add new MCP servers here, not in cockpit.

Where things live
-----------------
Path / DB helpers:        runtime.py
Schema migration:         runtime.apply_schema_migration
Numeric recognition:      runtime.METRIC_RE, NUMBER_RE, extract_metric_tokens
Component bootstrap:      runtime.KNOWN_BOOTSTRAP_COMPONENTS, bootstrap_all
Pure file ops:            heldout.py (compute_manifest etc.)
CLI entry shim:           heldout.main -> verify_mcp.heldout_cli.main

Do NOT
------
- Import from memory_mcp, verify_mcp, or cockpit at module level. The CLI
  forwarder in heldout.main does the import lazily; that is the only
  permitted exception.
- Add SQL DDL to runtime.py for business tables. Each component owns its
  own schema in its own db.py.
- Hard-code paths into the project tree. Always go through state_db_path,
  heldout_root, or runtime_path.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "5.1.2"
