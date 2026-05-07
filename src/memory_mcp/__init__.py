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
mem_nodes              [core]      Hypothesis-graph nodes; the ``kind`` field carries
                                   the domain (hypothesis / proposition /
                                   proof_skeleton / proof_snippet etc).
                                   ``elo_score`` is read-only legacy.
mem_edges              [core]      Parent-of and cross-edges (supports / refutes /
                                   contradicts).
mem_judgements         [core]      Legacy pairwise-judgement ledger (kept for compat).
mem_bt_ratings         [core]      Canonical Bradley-Terry strength + posterior
                                   variance. Same-kind comparison only.
mem_bt_comparisons     [core]      Append-only ledger of every BT comparison applied.
mem_failures           [core]      Cross-domain trigger / symptom / cause / resolution
                                   + signature dedup. ``domain`` column gates filtering;
                                   matching itself is domain-free.
mem_failures_fts       [core]      FTS5 index over mem_failures for match_signatures.
mem_lit_compressed     [core]      Structured paper compressions; trust-weighted BM25.
mem_lit_fts            [core]      FTS5 over the compression for query_literature.
mem_snapshots          [core]      Frozen graph snapshots used by replay. Payload covers
                                   both trunks: empirical frontier (question/hypothesis)
                                   plus proof frontier (proposition) and prv_* aggregates
                                   (corpus count, recent drafts/manifests/lean attempts).
                                   prv_* reads are defensively wrapped so legacy v3.0 DBs
                                   still snapshot cleanly with empty proof sections.
mem_replay_branches    [core]      Counterfactual branches; never mutate the main graph.
meta_calibration       [core]      Per-agent reliability-diagram buckets.

Domain labels (see ADR 0008 + architecture.md §13)
--------------------------------------------------
[core]      Domain-agnostic; usable from either trunk.
[empirical] Only meaningful in the ML / reproducibility workflow (see verify_mcp).
[proof]     v4.0 addition; lives in prove_mcp.

memory_mcp is entirely [core] — the trunk is the kind written into
``mem_nodes.kind`` and the value passed in ``mem_failures.domain``.

Critical invariants
-------------------
- ``mem_bt_ratings`` is the canonical hypothesis ranking; new readers prefer
  ``strength``, ``strength_var``, ``n_comparisons``. ``mem_nodes.elo_score``
  is kept only for v0.2 backward compatibility.
- ``record_judgement`` dual-writes both the legacy mem_judgements ledger
  AND the new mem_bt_comparisons ledger via _bt_apply_comparison.
- BT comparisons (``_bt_apply_comparison``) accept node kinds in
  ``BT_RANKABLE_KINDS`` (currently ``hypothesis`` and ``proof_skeleton``).
  Cross-kind comparison is forbidden so leaderboards stay coherent.
  ``record_judgement`` and ``judge_hypotheses`` remain hypothesis-only;
  ``update_bt_rating`` is the path proof-trunk callers should use for
  ``proof_skeleton`` comparisons.
- ``get_bt_leaderboard(kind=...)`` and
  ``expected_information_gain(kind=...)`` default to ``hypothesis`` for
  v3.0 backward compat. Pass ``kind='proof_skeleton'`` for the proof
  leaderboard.
- ``suggest_pause_low_strength`` is dry-run by default. The env var
  ``RESEARCH_AGENT_AUTO_PRUNE=1`` is the only way to flip status to paused.
- ``replay_counterfactual`` MUST NOT mutate ``mem_nodes`` or
  ``mem_bt_ratings``; it only writes ``mem_replay_branches``.
- ``mem_failures.domain`` (``empirical`` | ``proof``) gates filtering;
  ``record_failure`` defaults to ``empirical`` for v3.0 compat,
  ``match_signatures`` defaults to cross-domain (``domain=None``) so a
  proof snippet failure can match a script failure and vice versa.
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
