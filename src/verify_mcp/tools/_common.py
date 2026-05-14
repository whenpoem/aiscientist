"""Shared helpers used by more than one verify_mcp.tools submodule.

A helper lives here only when at least two tools/ submodules need it. Domain-
specific helpers stay next to the tools that own them.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from claudescientist.runtime import emit_cockpit_event


def _emit_event(con, kind: str, payload: dict) -> None:
    """Emit a cockpit event from inside an open transaction.

    Tags every row with ``source="verify_mcp"`` (Phase E provenance) so
    the cockpit's Detail pane can surface "who emitted this" without
    needing to thread the source through every tool call site.
    """
    emit_cockpit_event(con, kind, payload, source="verify_mcp")


def _run_script(
    script_path: str,
    args: list[str],
    *,
    timeout_sec: int,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a Python script in a subprocess and capture its output."""
    script = Path(script_path)
    if not script.exists():
        raise FileNotFoundError(script)
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env=env,
    )
