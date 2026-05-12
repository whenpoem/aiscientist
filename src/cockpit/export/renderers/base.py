"""Renderer base protocol.

A renderer takes a ``Report`` and returns ``str`` (text for the
output format; the pipeline encodes to UTF-8 bytes). Renderers never
touch the filesystem or SQLite — that is the pipeline's job.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cockpit.export.dto.base import Report


@runtime_checkable
class Renderer(Protocol):
    """Render a Report to the renderer's target format."""

    extension: str
    """Lowercase file extension without the leading dot (e.g. ``"md"``)."""

    def render(self, report: Report) -> str:
        """Return the full file body as a string."""
        raise NotImplementedError
