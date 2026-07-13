from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
skill_eval = importlib.import_module("build_skill_contract_eval")


def test_contract_eval_compares_new_skill_to_old_skill(tmp_path):
    benchmark_path = skill_eval.build(tmp_path / "review")
    payload = json.loads(benchmark_path.read_text(encoding="utf-8"))

    configurations = {run["configuration"] for run in payload["runs"]}
    assert configurations == {"new_skill", "old_skill"}
    assert set(payload["run_summary"]) == {"new_skill", "old_skill", "delta"}
    assert payload["run_summary"]["new_skill"]["pass_rate"]["mean"] == 1.0
    assert payload["run_summary"]["old_skill"]["pass_rate"]["mean"] < 1.0
    assert all(
        "not an independent model execution" in run["notes"][0]
        for run in payload["runs"]
    )
