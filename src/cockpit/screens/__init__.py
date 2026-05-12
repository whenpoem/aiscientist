"""Cockpit screens — full-window views pushed onto the App's screen stack.

Distinct from ``modals/`` which are dialog-style overlays used for confirms
and small forms. Screens here take over the whole window for reading or
deep-diving content that doesn't fit comfortably in the main grid.
"""

from .detail import (
    DetailScreen,
    DetailSource,
    EventDetailSource,
    NodeDetailSource,
    TabRowDetailSource,
)
from .splash import SplashScreen
from .welcome import WelcomeScreen

__all__ = [
    "DetailScreen",
    "DetailSource",
    "NodeDetailSource",
    "EventDetailSource",
    "TabRowDetailSource",
    "SplashScreen",
    "WelcomeScreen",
]
