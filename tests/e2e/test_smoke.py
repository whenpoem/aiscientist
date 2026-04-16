from __future__ import annotations

from fastapi.testclient import TestClient


def test_cockpit_smoke(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    server = workspace["cockpit.server"]

    hypothesis = memory_impl.propose_hypothesis("Try dropout scaling for ViT")

    with TestClient(server.app) as client:
        graph = client.get("/graph")
        assert graph.status_code == 200
        assert graph.json()["nodes"][0]["node_id"] == hypothesis["node_id"]

        queued = client.post(
            "/intervene",
            json={"kind": "reject", "target": hypothesis["node_id"], "payload": "stop this direction"},
        )
        assert queued.status_code == 200
        assert queued.json() == {"queued": True}
