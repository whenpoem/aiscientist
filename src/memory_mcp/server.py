"""Production entrypoint for memory_mcp."""

from __future__ import annotations

from fastmcp import FastMCP

from . import impl

mcp = FastMCP("memory")
mcp.tool(impl.propose_hypothesis)
mcp.tool(impl.attach_evidence)
mcp.tool(impl.mark_refuted)
mcp.tool(impl.get_active_frontier)
mcp.tool(impl.get_ancestors)
mcp.tool(impl.record_failure)
mcp.tool(impl.match_signatures)
mcp.tool(impl.ingest_paper)
mcp.tool(impl.query_literature)
mcp.tool(impl.find_baselines_for)


if __name__ == "__main__":
    mcp.run()

