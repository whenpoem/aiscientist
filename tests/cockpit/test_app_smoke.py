from __future__ import annotations

import pytest

from cockpit import data as cockpit_data
from cockpit.app import CockpitApp
from cockpit.panes import HypothesisTreePane


@pytest.mark.asyncio
async def test_cockpit_app_smoke(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    verify_impl = workspace["verify_mcp.impl"]

    root = memory_impl.propose_hypothesis("Tune dropout for ViT")
    memory_impl.attach_evidence(root["node_id"], "Held-out accuracy moved up", "supports")
    verify_impl.pin_metric(
        claim="accuracy",
        value="0.93",
        session_id="imagenet",
        source_command="train.py",
        note="seed 0",
    )

    app = CockpitApp()

    async with app.run_test() as pilot:
        tree = app.query_one(HypothesisTreePane)
        assert tree.visible_node_ids()
        assert app.selected_node_id is not None

        await pilot.press("j")
        assert tree.current_node_id() is not None

        await pilot.press("p")
        await pilot.press(*list("imagenet"))
        await pilot.press("tab")
        await pilot.press(*list("accuracy"))
        await pilot.press("tab")
        await pilot.press(*list("0.94"))
        await pilot.press("enter")

        await pilot.press("H")
        await pilot.press("y")

        claims = app.tabs_pane.claims_rows
        assert any(row["metric"] == "accuracy" for row in claims)

    assert cockpit_data.fetch_counts()["interventions"] >= 1
    events = cockpit_data.fetch_new_events(0)
    assert any(
        event["kind"] == "intervention" and event["payload"].get("kind") == "halt"
        for event in events
    )
