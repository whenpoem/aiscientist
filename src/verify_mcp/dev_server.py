"""Dev entrypoint for verify_mcp with hot-reloaded tool bodies."""

from __future__ import annotations

import importlib
import os

from fastmcp import FastMCP

from . import impl as _impl_module

mcp = FastMCP("verify-dev")


def _impl():
    global _impl_module
    if os.environ.get("RESEARCH_AGENT_DEV") == "1":
        _impl_module = importlib.reload(_impl_module)
    return _impl_module


@mcp.tool
def leakage_check(script_path: str | None = None, script_text: str | None = None) -> dict:
    """Run the leakage detector against a file path or raw script text."""
    return _impl().leakage_check(script_path=script_path, script_text=script_text)


@mcp.tool
def record_provenance(claim: str, value: str, session_id: str, source_command: str = "") -> dict:
    """Store provenance for a numeric claim."""
    return _impl().record_provenance(claim, value, session_id, source_command=source_command)


@mcp.tool
def check_provenance(claim: str) -> dict:
    """Return the latest provenance evidence for a claim."""
    return _impl().check_provenance(claim)


if __name__ == "__main__":
    mcp.run()

