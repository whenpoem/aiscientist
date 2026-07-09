"""Production entrypoint for prove_mcp."""

from __future__ import annotations

from fastmcp import FastMCP

from . import impl

mcp = FastMCP("prove")

for tool_name in impl.TOOL_NAMES:
    mcp.tool(getattr(impl, tool_name))


if __name__ == "__main__":
    mcp.run(show_banner=False, log_level="ERROR")
