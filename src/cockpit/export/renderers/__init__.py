"""Renderer layer — turns a Report DTO into bytes for a target format.

Two renderers ship in v4.2:

- ``markdown.MarkdownRenderer`` — pure stdlib, ``.md`` output. Plays
  well with editor previews (VS Code, Obsidian, GitHub).
- ``html.HtmlRenderer`` — self-contained single ``.html`` file with
  inline CSS. No CDN, no JS framework. PortfolioReport gets a flex
  column layout; everything else stacks vertically.

Adding a new format is one new class implementing the ``Renderer``
protocol plus an entry in the ``RENDERERS`` dict.
"""

from __future__ import annotations

from cockpit.export.renderers.base import Renderer
from cockpit.export.renderers.html import HtmlRenderer
from cockpit.export.renderers.markdown import MarkdownRenderer

RENDERERS = {
    "md": MarkdownRenderer(),
    "html": HtmlRenderer(),
}

__all__ = [
    "RENDERERS",
    "HtmlRenderer",
    "MarkdownRenderer",
    "Renderer",
]
