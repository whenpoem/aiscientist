from __future__ import annotations


def test_budget_check_with_no_config_allows_request(workspace):
    impl = workspace["verify_mcp.impl"]
    result = impl.budget_check(
        scope="session", resource="wallclock_sec", requested=10.0
    )
    assert result["allowed"] is True
    assert result["reason"] == "no_budget_configured"


def test_budget_consume_creates_row_and_decrements(workspace):
    impl = workspace["verify_mcp.impl"]
    first = impl.budget_consume(
        scope="session",
        resource="wallclock_sec",
        amount=5.0,
        limit_value=20.0,
    )
    assert first["ok"] is True
    assert first["used"] == 5.0
    assert first["remaining"] == 15.0

    second = impl.budget_consume(
        scope="session",
        resource="wallclock_sec",
        amount=12.0,
    )
    assert second["ok"] is True
    assert second["used"] == 17.0


def test_budget_consume_blocks_overflow(workspace):
    impl = workspace["verify_mcp.impl"]
    impl.budget_consume(
        scope="session",
        resource="llm_tokens",
        amount=80.0,
        limit_value=100.0,
    )
    blocked = impl.budget_consume(
        scope="session",
        resource="llm_tokens",
        amount=50.0,
    )
    assert blocked["ok"] is False
    assert blocked["error"] == "budget_exceeded"
    assert blocked["used"] == 80.0


def test_budget_check_after_consume_is_consistent(workspace):
    impl = workspace["verify_mcp.impl"]
    impl.budget_consume(
        scope="hypothesis:hyp_x",
        resource="heldout_queries",
        amount=2,
        limit_value=5,
    )
    state = impl.budget_check(
        scope="hypothesis:hyp_x", resource="heldout_queries", requested=3
    )
    assert state["allowed"] is True
    assert state["remaining"] == 3.0

    blocked = impl.budget_check(
        scope="hypothesis:hyp_x", resource="heldout_queries", requested=4
    )
    assert blocked["allowed"] is False
    assert blocked["action_if_denied"] == "halt"


def test_budget_check_respects_window(workspace):
    impl = workspace["verify_mcp.impl"]

    impl.budget_consume(
        scope="session",
        resource="llm_tokens",
        amount=0,
        limit_value=100,
        window="session",
    )
    impl.budget_consume(
        scope="session",
        resource="llm_tokens",
        amount=0,
        limit_value=1,
        window="daily",
    )

    session_state = impl.budget_check(
        scope="session",
        resource="llm_tokens",
        requested=50,
    )
    assert session_state["allowed"] is True
    assert session_state["window"] == "session"
    assert session_state["remaining"] == 100.0

    daily_state = impl.budget_check(
        scope="session",
        resource="llm_tokens",
        requested=2,
        window="daily",
    )
    assert daily_state["allowed"] is False
    assert daily_state["window"] == "daily"


def test_budget_consume_rejects_unknown_resource(workspace):
    impl = workspace["verify_mcp.impl"]
    raised = False
    try:
        impl.budget_consume(
            scope="session", resource="qubits", amount=1.0, limit_value=10.0
        )
    except ValueError:
        raised = True
    assert raised


def test_budget_overflow_emits_cockpit_event(workspace):
    impl = workspace["verify_mcp.impl"]
    cockpit_data = workspace.get("cockpit.data")
    if cockpit_data is None:
        return

    impl.budget_consume(
        scope="session",
        resource="disk_mb",
        amount=80.0,
        limit_value=100.0,
    )
    impl.budget_consume(scope="session", resource="disk_mb", amount=50.0)

    events = cockpit_data.fetch_new_events(0)
    kinds = [event["kind"] for event in events]
    assert "budget_exceeded" in kinds
