"""Cockpit package."""

from __future__ import annotations

from .app import CockpitApp, main, render_snapshot
from .mcp_server import mcp

__all__ = ["CockpitApp", "main", "mcp", "render_snapshot"]
