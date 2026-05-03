"""memory_mcp.impl - Re-export surface for tools split across tools/*.

The actual implementations live in :mod:`memory_mcp.tools`. This module
exists to preserve the import path ``from memory_mcp.impl import <tool>``
used by tests and ``server.py``. Do not add new logic here; add it under
``tools/`` next to its domain peers.
"""

from __future__ import annotations

from .db import bootstrap as bootstrap

# ruff: noqa: F401  (every import below is an intentional re-export)
from .tools.bt import (
    expected_information_gain,
    get_bt_leaderboard,
    judge_hypotheses,
    record_judgement,
    resume_branch,
    suggest_pause_low_strength,
    update_bt_rating,
)
from .tools.calibration import calibration_report, record_calibration
from .tools.failures import find_contradictions, match_signatures, record_failure
from .tools.graph import (
    attach_evidence,
    get_active_frontier,
    get_ancestors,
    mark_refuted,
    propose_hypothesis,
)
from .tools.literature import find_baselines_for, ingest_paper, query_literature
from .tools.replay import list_replay_branches, replay_counterfactual, snapshot

TOOL_NAMES = [
    "propose_hypothesis",
    "attach_evidence",
    "mark_refuted",
    "get_active_frontier",
    "get_ancestors",
    "judge_hypotheses",
    "record_judgement",
    "record_failure",
    "match_signatures",
    "find_contradictions",
    "snapshot",
    "ingest_paper",
    "query_literature",
    "find_baselines_for",
    "update_bt_rating",
    "get_bt_leaderboard",
    "suggest_pause_low_strength",
    "resume_branch",
    "expected_information_gain",
    "record_calibration",
    "calibration_report",
    "replay_counterfactual",
    "list_replay_branches",
]

bootstrap()
