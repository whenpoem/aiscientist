from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp.client import Client
from fastmcp.client.transports import UvStdioTransport

from cockpit import data as cockpit_data


@pytest.mark.asyncio
async def test_cockpit_mcp_server_stdio_tools(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    root = memory_impl.propose_hypothesis("Check stdio transport")

    repo_root = Path(__file__).resolve().parents[2]
    transport = UvStdioTransport(
        "cockpit.mcp_server",
        module=True,
        project_directory=repo_root,
    )

    async with Client(transport) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        assert {
            "push_graph_delta",
            "queue_intervention",
            "record_note",
            # v5.0 Activity Streaming atomic tools.
            "set_phase",
            "narrate",
        } <= tool_names

        pushed = await client.call_tool(
            "push_graph_delta",
            {
                "node_id": root["node_id"],
                "kind": "hypothesis",
                "text": "Check stdio transport",
            },
        )
        queued = await client.call_tool(
            "queue_intervention",
            {
                "kind": "reject",
                "target": root["node_id"],
                "payload": "not enough evidence",
            },
        )
        noted = await client.call_tool("record_note", {"text": "stdio smoke"})

    assert "ok" in str(pushed).lower()
    assert "ok" in str(queued).lower()
    assert "ok" in str(noted).lower()

    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "graph_delta" in kinds
    assert "intervention" in kinds
    assert "note" in kinds
