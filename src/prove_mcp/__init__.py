"""prove_mcp - Statistical proof generation trunk (v4.0).

Owns the proof-trunk corpus, retrieval, segmentation, diagnosis, global
correction, and Lean reinsurance triage. The proof-trunk counterpart to
the empirical ``verify_mcp`` server. See [ADR 0008] and architecture.md
§13 for the two-trunk architecture this module participates in.

Cross-trunk cooperation flows through the four shared interfaces in the
core (one tree, one failure ledger, one BT leaderboard, one reviewer);
this module never reaches into ``ver_*`` directly and writes its own
``prv_*`` tables.

One explicit shared-core exception exists: ``tools.nodes`` is the proof
trunk's sanctioned writer for proof-domain ``mem_nodes`` / ``mem_edges``
rows and seed ``mem_bt_ratings`` rows. That exception is narrow and
documented in the module; all other proof-trunk files must treat mem_*
tables as read-only or go through public memory tools.

Public surface
--------------
Tools (exposed via MCP):  see TOOL_NAMES in impl.py
Schema:                   schema.sql (loaded by db.bootstrap)
Bootstrap:                db.bootstrap()  (registered in
                          runtime.KNOWN_BOOTSTRAP_COMPONENTS)
Embedding adapter:        embedding.py  (Mock | Local | OpenAI;
                          RESEARCH_AGENT_EMBED_BACKEND env var)

Owned tables (prv_*)
--------------------
prv_corpus_problems       [proof] StatEval-style retrieval corpus.
prv_corpus_keywords       [proof] Per-problem lexical+semantic keywords with
                                 embeddings; the (backend, model, dim)
                                 triple is pinned per row so cross-model
                                 retrieval can be safely refused (ADR 0010).
prv_diagnostic_manifests  [proof] Per-draft snippet diagnoses + manifest
                                 lifecycle (open / empty / applied).
prv_lean_attempts         [proof] Audit trail of every Lean reinsurance
                                 attempt (verified / failed / timeout +
                                 source + duration_sec). Designed to be
                                 paired with a ``verify_mcp.budget_check``
                                 call before the attempt and a
                                 ``budget_consume`` after; see
                                 .claude/agents/prover.md § Budget for
                                 the contract.

Critical invariants
-------------------
- Cross-(backend, model, dim) mixing is forbidden. ``ingest_proof_corpus``
  records the active triple per keyword row; ``retrieve_skeletons`` rejects
  rows whose triple differs from the active configuration. To switch any
  leg of the triple, run ``scripts/reindex_proof_corpus.py`` (the cockpit
  surfaces a one-time hint when it detects a mismatch).
- Cross-domain failure matching belongs to ``mem_failures.domain``, not
  to a prv_* table. This module asks ``memory_mcp.match_signatures``
  with ``domain='proof'`` for snippet diagnosis (P3+).
- Bidirectional max-matching cosine score follows StatProver's
  formulation (architecture.md §13): the average of ``Sim(A→B)`` and
  ``Sim(B→A)``, where each direction averages the max cosine of every
  source keyword across all target keywords. This rewards strong local
  matches over generic terminology overlap.
- ``record_lean_attempt`` is intentionally a pure log: it does NOT
  call ``attach_evidence`` or ``record_failure`` on the caller's
  behalf. The prover agent's prompt explicitly performs those
  cross-trunk writes so each side effect is auditable in cockpit_events.

Where things live
-----------------
Tool re-export shell:     impl.py (do not add new logic here)
Embedding adapters:       embedding.py
Schema + bootstrap:       db.py + schema.sql
Corpus tools:             tools/corpus.py (ingest, list)
Retrieval tools:          tools/retrieval.py (skeleton matching)
Shared helpers:           tools/_common.py (event emission, vector codec)

Do NOT
------
- Reach into ``mem_*`` or ``ver_*`` tables directly. The only write
  exception is ``tools.nodes`` creating proof-domain graph rows in the
  shared core. Use the documented cross-trunk interfaces everywhere else;
  write cross-domain signals through ``cockpit_events`` (emit via
  runtime.emit_cockpit_event).
- Add module-level imports of memory_mcp, verify_mcp, or cockpit. The
  prove_mcp package must remain consumable in isolation.
- Pipeline-ise the toolset. ADR 0007 binds; every public tool is an
  atomic verb. Convenience wrappers are allowed but must declare
  themselves as wrappers in their docstring.
"""
