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


@pytest.mark.asyncio
async def test_filter_escape_clears_active_tree_filter(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")
    memory_impl.propose_hypothesis("Increase batch size")

    app = CockpitApp()

    async with app.run_test() as pilot:
        tree = app.query_one(HypothesisTreePane)

        await pilot.press("/")
        await pilot.press(*list("dropout"))
        await pilot.press("enter")

        assert app._pane_filters["tree"] == "dropout"
        assert len(tree.visible_node_ids()) == 1
        assert "filter: dropout" in tree.border_title

        await pilot.press("/")
        await pilot.press("escape")

        assert app._pane_filters["tree"] == ""
        assert len(tree.visible_node_ids()) == 2
        assert "filter:" not in tree.border_title


@pytest.mark.asyncio
async def test_language_toggle_localizes_core_tui_labels(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()

    async with app.run_test() as pilot:
        assert "Hypothesis Tree" in app.tree_pane.border_title

        await pilot.press("L")

        assert app.lang == "zh"
        assert "假设树" in app.tree_pane.border_title
        assert "节点详情" in app.detail_pane.border_title
        assert "研究座舱" in app.status_bar.current_text
        assert "切换语言" in app.context_bar.current_text


@pytest.mark.asyncio
async def test_event_dispatch_refreshes_only_affected_panes(workspace, monkeypatch):
    memory_impl = workspace["memory_mcp.impl"]
    memory_impl.propose_hypothesis("Tune dropout for ViT")

    app = CockpitApp()

    async with app.run_test():
        counters = {
            "graph": 0,
            "failures": 0,
            "claims": 0,
            "literature": 0,
            "counts": 0,
            "detail": 0,
        }

        monkeypatch.setattr(
            app,
            "_refresh_graph",
            lambda: counters.__setitem__("graph", counters["graph"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_failures",
            lambda: counters.__setitem__("failures", counters["failures"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_claims",
            lambda: counters.__setitem__("claims", counters["claims"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_literature",
            lambda: counters.__setitem__("literature", counters["literature"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_counts",
            lambda: counters.__setitem__("counts", counters["counts"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_detail",
            lambda: counters.__setitem__("detail", counters["detail"] + 1),
        )

        app._dispatch_events(
            [
                {"kind": "graph_delta"},
                {"kind": "failure_added"},
                {"kind": "seed_run_recorded"},
            ]
        )

        assert counters == {
            "graph": 1,
            "failures": 1,
            "claims": 1,
            "literature": 0,
            "counts": 1,
            "detail": 1,
        }
