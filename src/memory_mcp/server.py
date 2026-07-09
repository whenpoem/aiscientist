"""Production entrypoint for memory_mcp."""

from __future__ import annotations

from fastmcp import FastMCP

from . import impl

mcp = FastMCP("memory")

for tool_name in impl.TOOL_NAMES:
    mcp.tool(getattr(impl, tool_name))


if __name__ == "__main__":
    mcp.run(show_banner=False, log_level="ERROR")
