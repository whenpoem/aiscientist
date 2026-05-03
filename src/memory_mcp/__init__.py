"""memory_mcp - Hypothesis graph, Bradley-Terry ranking, and supporting memory.

Owns the hypothesis graph, the BT online tournament, the failure ledger, the
compressed literature index, the calibration ledger, and the snapshot /
counterfactual replay surface. Exposes 23 MCP tools through ``impl.py``;
implementations live under ``tools/`` and are domain-grouped.

Public surface
--------------
Tools (exposed via MCP):  see TOOL_NAMES in impl.py
Schema:                   schema.sql (loaded by db.bootstrap)
Bootstrap:                db.bootstrap()  (registered in
                          runtime.KNOWN_BOOTSTRAP_COMPONENTS)

Owned tables (mem_*, meta_*)
----------------------------
mem_nodes              Hypothesis-graph nodes; ``elo_score`` is read-only legacy.
mem_edges              Parent-of and cross-edges (supports / refutes / contradicts).
mem_judgements         Legacy pairwise-judgement ledger (kept for compat).
mem_bt_ratings         Canonical Bradley-Terry strength + posterior variance.
mem_bt_comparisons     Append-only ledger of every BT comparison applied.
mem_failures           Trigger / symptom / cause / resolution + signature dedup.
mem_failures_fts       FTS5 index over mem_failures for match_signatures.
mem_lit_compressed     Structured paper compressions; trust-weighted BM25.
mem_lit_fts            FTS5 over the compression for query_literature.
mem_snapshots          Frozen graph snapshots used by replay.
mem_replay_branches    Counterfactual branches; never mutate the main graph.
meta_calibration       Per-agent reliability-diagram buckets.

Critical invariants
-------------------
- ``mem_bt_ratings`` is the canonical hypothesis ranking; new readers prefer
  ``strength``, ``strength_var``, ``n_comparisons``. ``mem_nodes.elo_score``
  is kept only for v0.2 backward compatibility.
- ``record_judgement`` dual-writes both the legacy mem_judgements ledger
  AND the new mem_bt_comparisons ledger via _bt_apply_comparison.
- ``suggest_pause_low_strength`` is dry-run by default. The env var
  ``RESEARCH_AGENT_AUTO_PRUNE=1`` is the only way to flip status to paused.
- ``replay_counterfactual`` MUST NOT mutate ``mem_nodes`` or
  ``mem_bt_ratings``; it only writes ``mem_replay_branches``.
- Every state change that the cockpit needs to react to emits a
  ``cockpit_events`` row in the same SQL transaction.

Where things live
-----------------
Tool re-export shell:     impl.py (do not add new logic here)
Hypothesis graph tools:   tools/graph.py
Failure ledger + FTS:     tools/failures.py
Bradley-Terry online math + tools:   tools/bt.py
Calibration buckets:      tools/calibration.py
Snapshot + replay:        tools/replay.py
Literature compression:   tools/literature.py
Shared helpers:           tools/_common.py (_emit_event, _get_node, etc.)
Schema + bootstrap:       db.py + schema.sql

Do NOT
------
- Reach into ``ver_*`` or ``cockpit_*`` tables directly. Cross-module
  signals go through ``cockpit_events`` (emit via runtime.emit_cockpit_event).
- Add module-level imports of verify_mcp or cockpit. Memory must remain
  consumable in isolation.
- Skip ``_emit_event`` after a state change cockpit cares about (the live
  TUI relies on the polled event stream).
"""
