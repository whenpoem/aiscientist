"""Pane exports for the cockpit TUI."""

from __future__ import annotations

from .detail_pane import NodeDetailPane
from .events_pane import EventStreamPane
from .tabs_pane import RightTabsPane
from .timeline_pane import TimelinePane
from .tree_pane import HypothesisTreePane

__all__ = [
    "EventStreamPane",
    "HypothesisTreePane",
    "NodeDetailPane",
    "RightTabsPane",
    "TimelinePane",
]
