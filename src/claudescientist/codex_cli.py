"""Small compatibility helpers for invoking the Codex CLI."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def codex_command_prefix() -> list[str] | None:
    """Return an executable prefix that ``subprocess`` can launch directly.

    npm installs expose both an extensionless shim and ``codex.cmd`` on
    Windows. ``shutil.which('codex')`` can select the extensionless shim,
    which ``CreateProcess`` rejects with ``WinError 5``. Prefer the launchable
    Windows shims explicitly, while keeping the normal POSIX lookup.
    """
    candidates = ("codex.cmd", "codex.exe", "codex") if os.name == "nt" else ("codex",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return [resolved]
    return None


def codex_home() -> Path:
    """Resolve the config root used by the current Codex process."""
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


__all__ = ["codex_command_prefix", "codex_home"]
