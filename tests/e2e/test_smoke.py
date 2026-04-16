from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_cockpit_smoke(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    server = workspace["cockpit.server"]

    hypothesis = memory_impl.propose_hypothesis("Try dropout scaling for ViT")

    with TestClient(server.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True

        state = client.get("/state")
        assert state.status_code == 200
        snapshot = state.json()
        assert snapshot["graph"]["nodes"][0]["node_id"] == hypothesis["node_id"]
        assert snapshot["meta"]["mcp"]["transport"] == "http"
        assert snapshot["meta"]["mcp"]["url"].endswith("/mcp")

        mcp_probe = client.get("/mcp", follow_redirects=False)
        assert mcp_probe.status_code == 406

        last_event_id = snapshot["meta"]["last_event_id"]
        with client.websocket_connect(f"/ws/state?last_id={last_event_id}") as websocket:
            queued = client.post(
                "/intervene",
                json={
                    "kind": "reject",
                    "target": hypothesis["node_id"],
                    "payload": "stop this direction",
                },
            )
            assert queued.status_code == 200
            assert queued.json()["queued"] is True

            event = websocket.receive_json()
            assert event["kind"] == "intervention"
            assert event["payload"]["target"] == hypothesis["node_id"]

        interventions = client.get("/interventions")
        assert interventions.status_code == 200
        assert interventions.json()[0]["target"] == hypothesis["node_id"]


def test_claude_settings_register_http_cockpit_and_node_openalex():
    settings_path = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    cockpit = settings["mcpServers"]["cockpit"]["transport"]
    assert cockpit["type"] == "http"
    assert cockpit["url"].endswith("/mcp")

    openalex = settings["mcpServers"]["openalex"]
    assert openalex["command"] == "npx"
    assert openalex["args"] == ["-y", "openalex-research-mcp"]
