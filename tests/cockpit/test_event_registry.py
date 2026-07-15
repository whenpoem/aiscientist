from __future__ import annotations

from cockpit.activity import (
    BLOCKED_KINDS,
    FAILURE_KINDS,
    KIND_FAMILY,
    KIND_SEVERITY,
    SINGLETON_KINDS,
    TERMINAL_KINDS,
    TIME_BUCKET_KINDS,
)
from cockpit.event_registry import EVENT_REGISTRY, FAMILIES, refresh_targets_for


def test_activity_vocabulary_is_derived_from_event_registry():
    assert KIND_FAMILY == {
        kind: spec.family for kind, spec in EVENT_REGISTRY.items()
    }
    assert KIND_SEVERITY == {
        kind: spec.severity for kind, spec in EVENT_REGISTRY.items()
    }
    assert TERMINAL_KINDS == {
        kind for kind, spec in EVENT_REGISTRY.items() if spec.terminal_state == "done"
    }
    assert FAILURE_KINDS == {
        kind
        for kind, spec in EVENT_REGISTRY.items()
        if spec.terminal_state == "failed"
    }
    assert BLOCKED_KINDS == {
        kind
        for kind, spec in EVENT_REGISTRY.items()
        if spec.terminal_state == "blocked"
    }
    assert SINGLETON_KINDS == {
        kind for kind, spec in EVENT_REGISTRY.items() if spec.singleton
    }
    assert TIME_BUCKET_KINDS == {
        kind for kind, spec in EVENT_REGISTRY.items() if spec.time_bucket
    }


def test_event_specs_use_known_families_and_severities():
    assert EVENT_REGISTRY
    for spec in EVENT_REGISTRY.values():
        assert spec.family in FAMILIES
        assert spec.severity in {"info", "low", "medium", "high", "critical"}
        assert spec.terminal_state in {None, "done", "failed", "blocked"}


def test_refresh_routes_include_specific_and_common_targets():
    targets = refresh_targets_for(
        {"graph_delta", "claim_pinned", "proof_diagnosis_complete"}
    )
    assert {"graph", "claims", "diagnostics"} <= targets
    assert {"counts", "detail", "phase", "activity", "focus"} <= targets


def test_bt_fit_failure_is_a_blocking_risk_event():
    spec = EVENT_REGISTRY["bt_fit_failed"]
    assert spec.family == "risk"
    assert spec.severity == "critical"
    assert spec.terminal_state == "blocked"
    assert spec.singleton is True
