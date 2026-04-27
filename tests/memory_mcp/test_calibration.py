from __future__ import annotations


def test_record_calibration_buckets_predicted_p(workspace):
    impl = workspace["memory_mcp.impl"]
    result = impl.record_calibration(
        agent_name="researcher", predicted_p=0.72, realized_outcome=1
    )
    assert result["bucket"] == 0.75
    assert result["outcome"] == 1


def test_record_calibration_validates_inputs(workspace):
    impl = workspace["memory_mcp.impl"]

    raised = False
    try:
        impl.record_calibration(agent_name="researcher", predicted_p=1.5, realized_outcome=1)
    except ValueError:
        raised = True
    assert raised

    raised = False
    try:
        impl.record_calibration(agent_name="researcher", predicted_p=0.5, realized_outcome=2)
    except ValueError:
        raised = True
    assert raised

    raised = False
    try:
        impl.record_calibration(agent_name="   ", predicted_p=0.5, realized_outcome=0)
    except ValueError:
        raised = True
    assert raised


def test_calibration_report_aggregates_buckets(workspace):
    impl = workspace["memory_mcp.impl"]

    # researcher claims 0.72 prob (-> bucket 0.75) -> 7 wins out of 10 trials.
    for _ in range(7):
        impl.record_calibration("researcher", 0.72, 1)
    for _ in range(3):
        impl.record_calibration("researcher", 0.72, 0)

    report = impl.calibration_report("researcher")
    assert report["agent_name"] == "researcher"
    assert report["total_predictions"] == 10
    assert any(
        bucket["predicted_p"] == 0.75 and bucket["observed_p"] == 0.7
        for bucket in report["buckets"]
    )
    assert report["max_drift"] >= 0.0


def test_calibration_report_brier_score_well_calibrated_close_to_zero(workspace):
    impl = workspace["memory_mcp.impl"]

    # 50% predictions with 50% realized => Brier score around 0.25.
    for _ in range(20):
        impl.record_calibration("reviewer", 0.5, 1)
    for _ in range(20):
        impl.record_calibration("reviewer", 0.5, 0)

    report = impl.calibration_report("reviewer")
    # Brier score is bounded in [0, 1]; for this distribution it's exactly 0.25.
    assert 0.24 <= report["brier_score"] <= 0.26


def test_calibration_report_aggregates_across_agents_when_none(workspace):
    impl = workspace["memory_mcp.impl"]
    impl.record_calibration("a", 0.6, 1)
    impl.record_calibration("b", 0.6, 0)
    report = impl.calibration_report()
    assert report["agent_name"] is None
    assert report["total_predictions"] == 2
