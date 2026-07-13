from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".claude" / "skills"
TRIGGER_CASES = ROOT / "tests" / "fixtures" / "skill_trigger_cases_v51.json"


@pytest.mark.parametrize("name", ["research-sop", "debug-sop", "writeup-sop"])
def test_core_skill_has_realistic_evals(name: str) -> None:
    payload = json.loads((SKILLS / name / "evals" / "evals.json").read_text())
    assert payload["skill_name"] == name
    assert len(payload["evals"]) >= 3
    assert all(item["prompt"] and item["expected_output"] for item in payload["evals"])
    assert all(len(item["expectations"]) >= 3 for item in payload["evals"])


def test_research_skill_is_plugin_independent_and_recoverable() -> None:
    text = (SKILLS / "research-sop" / "SKILL.md").read_text().lower()
    required = (
        "custom `researcher`",
        "optional helpers",
        "interrupted work",
        "family_id",
        "run manifest",
        "interval_calibrated=false",
        "completion criteria",
        "claudescientist cockpit --workspace",
    )
    assert all(fragment in text for fragment in required)


def test_debug_skill_preserves_diagnosis_boundary_and_failure_branches() -> None:
    text = (SKILLS / "debug-sop" / "SKILL.md").read_text().lower()
    required = (
        "diagnosis request",
        "minimal reproduction",
        "one explanatory variable at a time",
        "cannot reproduce",
        "flaky",
        "external dependency failure",
        "record_failure",
        "completion criteria",
    )
    assert all(fragment in text for fragment in required)


def test_writeup_skill_closes_empirical_and_proof_claims() -> None:
    text = (SKILLS / "writeup-sop" / "SKILL.md").read_text().lower()
    required = (
        "claim manifest",
        "check_provenance",
        "refresh_claim",
        "family_id",
        "baseline_fairness",
        "uncalibrated approximate posterior",
        "unverified",
        "reviewer json",
        "completion criteria",
    )
    assert all(fragment in text for fragment in required)


def test_core_skill_trigger_corpus_has_positive_and_near_miss_coverage() -> None:
    cases = json.loads(TRIGGER_CASES.read_text(encoding="utf-8"))
    names = {"research-sop", "debug-sop", "writeup-sop"}

    assert len(cases) >= 30
    assert all(len(case["prompt"]) >= 80 for case in cases)
    for case in cases:
        should = set(case["should_trigger"])
        should_not = set(case["should_not_trigger"])
        assert should <= names
        assert should_not <= names
        assert should.isdisjoint(should_not)
        assert should | should_not == names

    for name in names:
        positives = [case for case in cases if name in case["should_trigger"]]
        negatives = [case for case in cases if name in case["should_not_trigger"]]
        assert len(positives) >= 10
        assert len(negatives) >= 10
