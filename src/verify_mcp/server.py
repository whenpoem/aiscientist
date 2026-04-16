"""Production entrypoint for verify_mcp."""

from __future__ import annotations

from fastmcp import FastMCP

from . import impl

mcp = FastMCP("verify")
mcp.tool(impl.leakage_check)
mcp.tool(impl.record_provenance)
mcp.tool(impl.check_provenance)


if __name__ == "__main__":
    mcp.run()

