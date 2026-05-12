"""Base dataclasses every Report DTO produces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReportSection:
    """One logical block inside a report.

    The renderer decides how to present a section — as a markdown
    ``##`` heading + body, an HTML ``<section>`` + ``<details>``, a
    side-by-side column in a portfolio HTML — but the DTO never picks
    those choices itself. ``meta`` carries kind-specific fields that
    renderers may opt into; unknown keys are ignored.
    """

    key: str
    title: str
    body: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Report:
    """Result of a DTO builder. Renderers consume this and write bytes.

    ``kind`` and ``format_`` (set by the pipeline, not the DTO) flow
    through to the file path and the ``cockpit_reports`` row. The
    builder fills ``kind`` so it travels with the data — renderers
    can branch on it for kind-specific styling (e.g. PortfolioReport
    needs side-by-side HTML, others stack vertically).
    """

    kind: str
    node_id: str
    title: str
    generated_at: str
    sections: tuple[ReportSection, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
