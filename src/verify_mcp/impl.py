"""verify_mcp.impl - Re-export surface for tools split across tools/*.

The actual implementations live in :mod:`verify_mcp.tools`. This module
exists to preserve the import path ``from verify_mcp.impl import <tool>``
used by tests and ``server.py``. Do not add new logic here; add it under
``tools/`` next to its domain peers.
"""

from __future__ import annotations

from .db import bootstrap as bootstrap

# ruff: noqa: F401  (every import below is an intentional re-export)
from .tools.budget import budget_check, budget_consume
from .tools.heldout import query_heldout
from .tools.leakage import leakage_check
from .tools.prereg import list_preregistrations, preregister, resolve_preregistration
from .tools.provenance import (
    check_provenance,
    pin_metric,
    record_provenance,
    refresh_claim,
)
from .tools.reporting import export_report
from .tools.verification import baseline_fairness, seed_perturb

TOOL_NAMES = [
    "leakage_check",
    "record_provenance",
    "check_provenance",
    "pin_metric",
    "seed_perturb",
    "baseline_fairness",
    "query_heldout",
    "refresh_claim",
    "preregister",
    "resolve_preregistration",
    "list_preregistrations",
    "budget_check",
    "budget_consume",
    # v4.2.0a2 (ADR 0009): generate cockpit report files on demand.
    "export_report",
]

bootstrap()
