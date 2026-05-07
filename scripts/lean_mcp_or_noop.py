#!/usr/bin/env python
"""Lean MCP auto-dispatch wrapper.

Claude Code spawns this script when settings.json declares the ``lean``
mcpServer. The wrapper inspects the local environment:

- If ``lake`` and ``lean`` are on PATH, exec / spawn the real
  ``lean-lsp-mcp`` and forward stdio.
- Otherwise print a one-line stderr explanation and exit 0.

The exit-0 path lets Claude Code register that the lean MCP is unavailable
without surfacing it as a session-fatal error. The prover agent's prompt
already handles the absence of ``mcp__lean__*`` tools by aborting cleanly.

Why a wrapper instead of leaving ``_lean`` disabled:

- Users who follow ``docs/setup-lean.md`` no longer need to hand-edit
  settings.json -- the wrapper notices the new lake + lean toolchain
  and starts forwarding automatically.
- Users who never install Lean see no startup error.
- The detection rule is conservative: both ``lake`` and ``lean`` must
  resolve via PATH. ``lean-lsp-mcp`` itself is invoked through
  ``uv tool run`` so it works whether or not ``~/.local/bin`` is on PATH.

This is intentionally small (no third-party deps) so it can run inside a
fresh ``uv sync`` venv without any optional extras installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404 -- argv is a fixed list, no shell.
import sys

_NEEDED_TOOLS = ("lake", "lean")


def _have_lean_toolchain() -> bool:
    """Return True iff the Lean toolchain (elan-installed lake + lean) is
    discoverable on PATH. We do NOT check for ``lean-lsp-mcp`` directly
    because users may rely on ``uv tool run`` to locate it."""
    return all(shutil.which(name) for name in _NEEDED_TOOLS)


def _spawn_real_mcp(extra_args: list[str]) -> int:
    """Spawn the real lean-lsp-mcp via ``uv tool run`` and forward stdio.

    On POSIX this uses ``os.execvp`` so the wrapper PID is replaced and
    Claude Code's pipe talks directly to lean-lsp-mcp. On Windows we fall
    back to ``subprocess.call`` because the platform's exec emulation
    sometimes drops stdio handles for stdio-MCP servers.
    """
    cmd = ["uv", "tool", "run", "lean-lsp-mcp", *extra_args]
    if os.name == "nt":
        return subprocess.call(cmd)  # noqa: S603 -- argv is a fixed list.
    os.execvp(cmd[0], cmd)
    return 0  # unreachable on POSIX


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if not _have_lean_toolchain():
        print(
            "lean MCP unavailable: install elan + mathlib per docs/setup-lean.md "
            "(this is non-fatal; the NL proof workflow does not require Lean).",
            file=sys.stderr,
        )
        return 0
    return _spawn_real_mcp(args)


if __name__ == "__main__":
    raise SystemExit(main())
