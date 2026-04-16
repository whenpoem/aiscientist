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

  matches = impl.match_signatures("possible leakage because the scaler saw train and test together")

  assert first["failure_id"] == matches[0]["failure_id"]
  assert matches[0]["resolution"] == "fit scaler on train only"

