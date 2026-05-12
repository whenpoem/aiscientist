"""Reports export pipeline for the cockpit (v4.2.0a2 / ADR 0009).

Generates dense report content (closure certificates, full proof
drafts, diagnostic reports, portfolio comparisons, cascade traces) as
markdown or HTML files under ``reports/``. Cockpit's Reports tab
indexes the generated files via the ``cockpit_reports`` table; users
open them in their own editor or browser. The cockpit never embeds a
renderer for these formats.

The pipeline is intentionally a small composition of three layers:

- ``dto/`` reads SQLite and produces a ``Report`` dataclass — pure
  data, no presentation concerns.
- ``renderers/`` consumes the DTO and writes bytes — pure
  presentation, no SQL.
- ``pipeline.generate`` glues the two, writes the file to disk,
  inserts the ``cockpit_reports`` row, and emits a
  ``report_generated`` cockpit event so the live TUI lights up.

The CLI in ``cli.py`` exposes ``python -m cockpit.export``.
"""

from __future__ import annotations

from cockpit.export.dto.base import Report, ReportSection
from cockpit.export.pipeline import FORMATS, KINDS, generate

__all__ = [
    "FORMATS",
    "KINDS",
    "Report",
    "ReportSection",
    "generate",
]
