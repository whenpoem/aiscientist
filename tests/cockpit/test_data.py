from __future__ import annotations

from cockpit import data as cockpit_data


def test_cockpit_data_layer_reads_existing_tables(workspace):
    memory_impl = workspace["memory_mcp.impl"]

    root = memory_impl.propose_hypothesis("Investigate dropout scaling")
    child = memory_impl.propose_hypothesis("Try higher dropout", parent_id=root["node_id"])
    memory_impl.attach_evidence(child["node_id"], "Validation improved", "supports")
    failure = memory_impl.record_failure("oom_batch_size", "OOM at batch 256")
    paper = memory_impl.ingest_paper(
        "paper-1",
        "manual",
        {
            "title": "Dropout in Vision Transformers",
            "year": 2024,
            "problem": "regularization",
            "method": "dropout search",
            "trust_level": 0.8,
        },
    )
    pin = cockpit_data.pin_metric_local(
        claim="accuracy",
        value="0.91",
        session_id="cifar10",
        source_command="train.py",
        note="baseline",
    )
    cockpit_data.refute_node(child["node_id"], "failed follow-up")

    intervention = cockpit_data.write_intervention("reject", child["node_id"], "too risky")
    cockpit_data.record_event("note", {"text": "remember to compare against baseline"})

    graph = cockpit_data.fetch_graph()
    assert graph.node(root["node_id"]) is not None
    assert graph.parents_of(child["node_id"]) == [root["node_id"]]
    assert graph.cross_edges_of(child["node_id"])
    assert root["node_id"] in graph.visible_ids()
    assert child["node_id"] not in graph.visible_ids()
    assert graph.visible_ids(show_refuted=True)[:2] == [root["node_id"], child["node_id"]]

    counts = cockpit_data.fetch_counts()
    assert counts["nodes"] >= 2
    assert counts["failures"] >= 1
    assert counts["events"] >= 3
    assert counts["interventions"] >= 1

    failures = cockpit_data.fetch_failures()
    assert failures[0]["failure_id"] == failure["failure_id"]

    claims = cockpit_data.fetch_claims()
    assert claims[0]["pin_id"] == pin["pin_id"]
    assert claims[0]["metric"] == "accuracy"
    assert claims[0]["dataset"] == "cifar10"
    assert claims[0]["seeds"] == "0/3"
    assert claims[0]["verified"] is False
    risks = cockpit_data.fetch_risks(claims=claims, failures=failures, graph=graph)
    assert any(row["category"] == "claim" and row["item"] == "accuracy" for row in risks)
    dashboard = cockpit_data.fetch_dashboard()
    assert dashboard["active_hypotheses"] >= 1
    assert dashboard["pinned_claims"] >= 1
    assert dashboard["risks"] >= 1

    literature = cockpit_data.fetch_literature()
    assert literature[0]["paper_id"] == paper["ingested"]
    assert literature[0]["task"] == "regularization"

    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "graph_delta" in kinds
    assert "failure_added" in kinds
    assert "claim_pinned" in kinds
    assert "literature_ingested" in kinds
    assert "intervention" in kinds
    assert "note" in kinds
    assert intervention["event_id"] in {events[-2]["id"], events[-1]["id"]}


def test_fetch_claims_treats_one_seed_suite_as_verified(workspace):
    impl = workspace["verify_mcp.impl"]
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "verify_mcp" / "fixtures" / "seed_stable.py"

    pin = impl.pin_metric(
        claim="test accuracy",
        value="0.875",
        session_id="seed-suite",
        source_command=str(fixture),
    )
    impl.seed_perturb(script_path=str(fixture), metric_pin_id=pin["pin_id"])

    claims = cockpit_data.fetch_claims()

    claim = next(row for row in claims if row["pin_id"] == pin["pin_id"])
    assert claim["seeds"] == "3/3"
    assert claim["verified"] is True


def test_fetch_new_events_bootstraps_recent_window(workspace):
    for index in range(2505):
        cockpit_data.record_event("note", {"index": index})

    events = cockpit_data.fetch_new_events(0)

    assert len(events) == 2000
    assert events[0]["payload"]["index"] == 505
    assert events[-1]["payload"]["index"] == 2504
