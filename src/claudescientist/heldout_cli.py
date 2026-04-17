"""Compatibility wrapper for the held-out dataset CLI."""

from __future__ import annotations

from .heldout import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
