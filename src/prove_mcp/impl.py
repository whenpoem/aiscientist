"""prove_mcp.impl - Re-export surface for tools split across tools/*.

The actual implementations live in :mod:`prove_mcp.tools`. This module
exists to preserve the import path ``from prove_mcp.impl import <tool>``
used by tests and ``server.py``. Do not add new logic here; add it under
``tools/`` next to its domain peers.
"""

from __future__ import annotations

from .db import bootstrap as bootstrap
from .tools.corpus import (
    corpus_backend_signatures,
    ingest_proof_corpus,
    list_corpus,
    reindex_corpus,
)

# ruff: noqa: F401  (every import below is an intentional re-export)
from .tools.correction import apply_correction, compose_correction_prompt
from .tools.diagnosis import (
    diagnose_snippet,
    finalize_manifest,
    list_diagnostic_manifests,
    register_diagnosis,
)
from .tools.lean_bridge import (
    list_lean_attempts,
    record_lean_attempt,
    triage_for_formalization,
)
from .tools.nodes import (
    list_proof_drafts,
    propose_proof_skeleton,
    propose_proposition,
    register_proof_draft,
)
from .tools.retrieval import retrieve_skeletons
from .tools.segmentation import list_proof_snippets, segment_proof

TOOL_NAMES = [
    # P2: corpus + retrieval
    "ingest_proof_corpus",
    "list_corpus",
    "retrieve_skeletons",
    # v4.2.0a0: corpus maintenance (ADR 0010)
    "reindex_corpus",
    "corpus_backend_signatures",
    # P3: NL workflow
    "propose_proposition",
    "propose_proof_skeleton",
    "register_proof_draft",
    "list_proof_drafts",
    "segment_proof",
    "list_proof_snippets",
    "diagnose_snippet",
    "register_diagnosis",
    "finalize_manifest",
    "list_diagnostic_manifests",
    "compose_correction_prompt",
    "apply_correction",
    # P4: Lean reinsurance
    "triage_for_formalization",
    "record_lean_attempt",
    "list_lean_attempts",
]

bootstrap()
