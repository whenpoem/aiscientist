"""Report DTO layer.

Each kind has a ``build_<kind>(node_id) -> Report`` factory. The
factory reads SQLite and produces a frozen dataclass that the
renderer layer turns into bytes. DTOs carry no presentation logic —
no rich text, no markup, no escaping. Renderers handle that.
"""

from __future__ import annotations

from cockpit.export.dto.base import Report, ReportSection
from cockpit.export.dto.cascade import build_cascade
from cockpit.export.dto.closure import build_closure
from cockpit.export.dto.diagnostic import build_diagnostic
from cockpit.export.dto.draft import build_draft
from cockpit.export.dto.portfolio import build_portfolio

BUILDERS = {
    "closure": build_closure,
    "draft": build_draft,
    "diagnostic": build_diagnostic,
    "portfolio": build_portfolio,
    "cascade": build_cascade,
}

__all__ = [
    "BUILDERS",
    "Report",
    "ReportSection",
    "build_cascade",
    "build_closure",
    "build_diagnostic",
    "build_draft",
    "build_portfolio",
]
