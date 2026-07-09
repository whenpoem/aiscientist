"""Dev entrypoint for prove_mcp with hot-reloaded tool bodies."""

from __future__ import annotations

import importlib
import inspect
import os
from functools import wraps

from fastmcp import FastMCP

from . import impl as _impl_module

mcp = FastMCP("prove-dev")


def _impl():
    global _impl_module
    if os.environ.get("RESEARCH_AGENT_DEV") == "1":
        _impl_module = importlib.reload(_impl_module)
    return _impl_module


def _wrap(tool_name: str):
    tool = getattr(_impl_module, tool_name)

    @wraps(tool)
    def wrapper(*args, **kwargs):
        return getattr(_impl(), tool_name)(*args, **kwargs)

    wrapper.__signature__ = inspect.signature(tool)
    return wrapper


for tool_name in _impl_module.TOOL_NAMES:
    globals()[tool_name] = mcp.tool(_wrap(tool_name))


if __name__ == "__main__":
    mcp.run(show_banner=False, log_level="ERROR")
