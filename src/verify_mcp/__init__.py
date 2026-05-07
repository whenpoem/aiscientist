"""verify_mcp - Verification, provenance, preregistration, sequestered data, budget.

Owns the verification stack: leakage detection, provenance with refreshable
DAG, multi-seed reproducibility, baseline fairness, sequestered-dataset
budgeted querying, preregistration with multiple-comparison
correction, and the resource ledger. Exposes 13 MCP tools through ``impl.py``;
implementations live under ``tools/`` and are domain-grouped.

Public surface
--------------
Tools (exposed via MCP):  see TOOL_NAMES in impl.py
Schema:                   inline in db.py (loaded by db.bootstrap)
Bootstrap:                db.bootstrap()  (registered in
                          runtime.KNOWN_BOOTSTRAP_COMPONENTS)
Sequestered-data CLI:     heldout_cli.main  (re-exported as
                          claudescientist.heldout.main for the documented
                          ``python -m claudescientist.heldout`` invocation)

Owned tables (ver_*, res_*)
---------------------------
ver_provenance         [empirical] Append-only numeric-claim ledger; the source of truth.
ver_metric_pins        [empirical] Pinned headline numbers; reviewer reads these on writeup.
ver_provenance_dag     [empirical] Per-claim input-file hashes; refresh_claim re-checks.
ver_seed_runs          [empirical] One row per seed_perturb invocation (mean / std / verdict).
ver_heldout_budgets    [empirical] Sequestered-dataset registration + remaining budget.
ver_heldout_queries    [empirical] One row per query_heldout invocation; FK to budgets.
ver_preregistrations   [empirical] Locked falsification targets + correction state.
res_budget_ledger      [empirical] Wallclock / tokens / heldout / disk budgets per scope.

Domain labels (see ADR 0008 + architecture.md §13)
--------------------------------------------------
[core]      Domain-agnostic; usable from either trunk.
[empirical] Only meaningful in the ML / reproducibility workflow.
[proof]     v4.0 addition; lives in prove_mcp.

verify_mcp is entirely [empirical]: every tool here is grounded in
ML reproducibility primitives (held-out splits, multi-seed perturbation,
metric pinning, baseline fairness, preregistered hypothesis testing).
Proof workflows have their own analogues in prove_mcp; cross-trunk
cooperation flows through the four shared interfaces documented in
architecture.md §13, not through this module.

Critical invariants
-------------------
- ``query_heldout`` is the only intended access path to sequestered data.
  Direct file reads are blocked by ``leakage_guard.py``. Failed model runs
  still consume reserved budget because the script was already authorised.
- The four anchors for an accepted numeric claim are: ``record_provenance``,
  a stable ``ver_seed_runs.verdict``, a ``status='met'``
  ``ver_preregistrations`` row, and a fresh ``ver_provenance_dag``.
- ``refresh_claim`` re-hashes input files and emits ``prov_dag_stale``
  events; stale provenance is a hard blocker for writeup.
- ``bh`` and ``bonferroni`` currently share the same Bonferroni-style
  correction in ``resolve_preregistration``; it runs against the count of
  *currently open* prereg rows, so the more open at once, the stricter the
  alpha each one must clear.
- ``budget_consume`` is the only writer of ``res_budget_ledger``;
  ``budget_check`` is read-only and must address the same
  ``(scope, resource, window)`` triple that consume writes.

Where things live
-----------------
Tool re-export shell:     impl.py (do not add new logic here)
Leakage detector wrapper: tools/leakage.py (delegates to verify_mcp.leakage)
Provenance + pin + DAG:   tools/provenance.py
Verification subprocesses: tools/verification.py (seed_perturb, fairness)
Sequestered query:        tools/heldout.py (FK to ver_heldout_budgets)
Preregistration correction: tools/prereg.py
Budget ledger:            tools/budget.py
Shared helpers:           tools/_common.py (_emit_event, _run_script)
Sequestered data CLI:     heldout.py + heldout_cli.py (owns ver_heldout_*)
AST leakage rules:        leakage.py (root, scan_file / scan_python)
Numeric normalizers:      provenance.py (re-exports from runtime)
Budget log parser:        budget.py (root, extract_budget / budget_ratios)
Schema + bootstrap:       db.py

Do NOT
------
- Reach into ``mem_*`` tables directly. Cross-module signals go through
  ``cockpit_events`` (emit via runtime.emit_cockpit_event).
- Add module-level imports of memory_mcp or cockpit. Verify must remain
  consumable in isolation.
- Bypass ``query_heldout`` to read sequestered data; that defeats the
  whole budget + manifest verification chain.
- Confuse ``verify_mcp.leakage`` (root, AST scanner) with
  ``verify_mcp.tools.leakage`` (the MCP tool wrapper) - both modules exist.
"""
