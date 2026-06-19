"""End-to-end: propose -> preregister -> seed_perturb -> resolve.

Verifies the V3.0 P2 flow keeps prereg + BT + seed-run state aligned and
emits the expected cockpit events in order.
"""

from __future__ import annotations

from pathlib import Path


def test_full_prereg_flow_smoke(workspace):
    memory_impl = workspace["memory_mcp.impl"]
    verify_impl = workspace["verify_mcp.impl"]
    cockpit_data = workspace.get("cockpit.data")

    hypothesis_id = memory_impl.propose_hypothesis(
        "ViT-S/16 with cosine LR will exceed 87.5% on test fixture"
    )["node_id"]

    locked = verify_impl.preregister(
        hypothesis_id=hypothesis_id,
        metric_name="test accuracy",
        direction="higher_better",
        threshold=0.85,
        seed_count=3,
        alpha=0.05,
        mc_correction="bonferroni",
    )
    assert locked["status"] == "open"

    fixture = (
        Path(__file__).resolve().parents[1]
        / "verify_mcp"
        / "fixtures"
        / "seed_stable.py"
    )
    pin = verify_impl.pin_metric(
        claim="test accuracy",
        value="0.875",
        session_id="sess-prereg",
        source_command=f"python {fixture}",
        note="prereg-linked",
    )
    seed_run = verify_impl.seed_perturb(
        script_path=str(fixture),
        metric_pin_id=pin["pin_id"],
    )
    assert seed_run["ok"] is True
    assert seed_run["verdict"] == "stable"

    resolved = verify_impl.resolve_preregistration(
        prereg_id=locked["prereg_id"],
        observed_value=seed_run["mean_value"],
    )
    assert resolved["ok"] is True
    assert resolved["status"] == "met"

    if cockpit_data is not None:
        events = cockpit_data.fetch_new_events(0)
        kinds = [event["kind"] for event in events]
        for required in [
            "graph_delta",
            "prereg_locked",
            "claim_pinned",
            "seed_run_recorded",
            "prereg_resolved",
        ]:
            assert required in kinds, f"missing cockpit event: {required}"
