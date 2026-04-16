from __future__ import annotations

from pathlib import Path


def test_leakage_detector_flags_concatenated_fit(workspace):
  impl = workspace["verify_mcp.impl"]
  fixture = Path(__file__).with_name("fixtures") / "leaky_scaler.py"

  result = impl.leakage_check(script_path=str(fixture))

  assert result["clean"] is False
  assert result["findings"][0]["rule"] == "fit_on_concatenated"


def test_leakage_detector_accepts_clean_pipeline(workspace):
  impl = workspace["verify_mcp.impl"]
  fixture = Path(__file__).with_name("fixtures") / "clean_pipeline.py"

  result = impl.leakage_check(script_path=str(fixture))

  assert result == {"clean": True, "findings": []}

