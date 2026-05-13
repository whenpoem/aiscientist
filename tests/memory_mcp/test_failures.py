from __future__ import annotations


def test_record_and_match_signatures(workspace):
    impl = workspace["memory_mcp.impl"]

    first = impl.record_failure(
        "scaler fit on concatenated split",
        "test metrics looked too good",
        "data leakage",
        "fit scaler on train only",
    )
    impl.record_failure(
        "cuda oom",
        "training crashed",
        "batch too large",
        "reduce batch size",
    )

    matches = impl.match_signatures(
        "possible leakage because the scaler saw train and test together"
    )

    assert first["failure_id"] == matches[0]["failure_id"]
    assert matches[0]["resolution"] == "fit scaler on train only"


def test_record_failure_deduplicates_by_signature_and_domain(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    first = impl.record_failure(
        "scaler fit on concatenated split",
        "test metrics looked too good",
        "data leakage",
        "fit scaler on train only",
    )
    second = impl.record_failure(
        "scaler fit on concatenated split",
        "test metrics looked too good",
        "data leakage",
        "fit scaler on train only",
    )

    assert second["failure_id"] == first["failure_id"]
    assert second["deduplicated"] is True

    con = db._connect()
    try:
        row = con.execute(
            "SELECT seen_count FROM mem_failures WHERE failure_id = ?",
            (first["failure_id"],),
        ).fetchone()
    finally:
        con.close()

    assert row["seen_count"] == 2
