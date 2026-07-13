"""Path resolution for generated reports.

Files land in ``<repo-root>/reports/`` by default. The location is
controlled by ``RESEARCH_AGENT_REPORTS_DIR`` so tests (and users who
want a different layout) can redirect without code change.

Filenames follow ``<node_short>-<kind>.<format>``. Re-running an
export against the same node + kind + format overwrites the existing
file — reports are reproducible, not append-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from claudescientist.runtime import workspace_root

ENV_REPORTS_DIR = "RESEARCH_AGENT_REPORTS_DIR"
DEFAULT_REPORTS_SUBDIR = "reports"


def reports_dir() -> Path:
    """Resolve the reports output directory.

    Honors ``RESEARCH_AGENT_REPORTS_DIR`` for tests / power users.
    Falls back to ``<repo-root>/reports`` so a Claude Code session launched
    from a subdirectory still writes to the same report index the cockpit
    will read. If repo-root detection fails, use cwd as a last resort.
    """
    override = os.environ.get(ENV_REPORTS_DIR)
    if override:
        return Path(override).resolve()
    return workspace_root() / DEFAULT_REPORTS_SUBDIR


def _short(node_id: str) -> str:
    """Short id used inside filenames. Keeps the prefix + first 6 hex chars."""
    if "_" not in node_id:
        return node_id[:10]
    prefix, suffix = node_id.split("_", 1)
    return f"{prefix}_{suffix[:6]}"


def report_filename(kind: str, node_id: str, format_: str) -> str:
    """Build a deterministic filename for a (kind, node, format) triple.

    The triple is treated as the natural key — exporting the same
    triple twice overwrites. That keeps the ``reports/`` directory
    bounded as the user iterates.
    """
    return f"{_short(node_id)}-{kind}.{format_}"


def report_path(kind: str, node_id: str, format_: str) -> Path:
    """Convenience: combine ``reports_dir()`` and ``report_filename()``."""
    return reports_dir() / report_filename(kind, node_id, format_)
