"""Dev entrypoint for verify_mcp with hot-reloaded tool bodies."""

from __future__ import annotations

import importlib
import inspect
import os
from functools import wraps

from fastmcp import FastMCP

from . import impl as _impl_module

mcp = FastMCP("verify-dev")


def _impl():
    global _impl_module
    if os.environ.get("RESEARCH_AGENT_DEV") == "1":
        _impl_module = importlib.reload(_impl_module)
    return _impl_module


def _build_tool(tool_name: str):
    impl_fn = getattr(_impl_module, tool_name)

    @wraps(impl_fn)
    def wrapper(*args, **kwargs):
        return getattr(_impl(), tool_name)(*args, **kwargs)

    wrapper.__signature__ = inspect.signature(impl_fn)
    return wrapper


for _tool_name in _impl_module.TOOL_NAMES:
    globals()[_tool_name] = mcp.tool(_build_tool(_tool_name))


if __name__ == "__main__":
    mcp.run()
