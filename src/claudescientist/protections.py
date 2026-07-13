"""Machine-readable protection-strength catalog.

``enforced`` means code or a configured lifecycle hook performs the check.
It is a product guardrail, not an adversarial operating-system security
boundary. ``agent_gated`` depends on an agent following its workflow, while
``advisory`` reports risk without blocking the action.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ProtectionLevel = Literal["enforced", "agent_gated", "advisory"]
PROTECTION_LEVELS: tuple[ProtectionLevel, ...] = (
    "enforced",
    "agent_gated",
    "advisory",
)


@dataclass(frozen=True)
class Protection:
    protection_id: str
    level: ProtectionLevel
    mechanism: str
    condition: str
    degradation: str


PROTECTIONS: tuple[Protection, ...] = (
    Protection(
        "sequestered_direct_access",
        "enforced",
        "leakage guard denies direct access to registered sequestered paths",
        "host hooks are installed and enabled",
        "without hooks, only the budgeted query policy and audit guidance remain",
    ),
    Protection(
        "destructive_shell",
        "enforced",
        "destructive command guard denies known destructive command patterns",
        "host hooks are installed and enabled",
        "without hooks, the host's normal command approval policy applies",
    ),
    Protection(
        "sequestered_budget",
        "enforced",
        "the sequestered query tool reserves budget before launching a model script",
        "sequestered access goes through the supported query tool",
        "direct access outside the tool is not covered when hooks are disabled",
    ),
    Protection(
        "provenance_freshness",
        "enforced",
        "refresh_claim re-hashes run files and compares Git and environment state",
        "the result was recorded with v5.1 run manifests",
        "legacy results without a manifest are reported as unchecked",
    ),
    Protection(
        "confirmatory_preregistration",
        "agent_gated",
        "research and write-up workflows require a met preregistration",
        "the active agent follows research-sop and writeup-sop",
        "direct tool or file use can bypass the workflow gate",
    ),
    Protection(
        "reviewer_signoff",
        "agent_gated",
        "reviewer rejects unsupported publication-critical claims",
        "the manuscript is routed through the reviewer agent or skill",
        "the reviewer is not a filesystem write security boundary",
    ),
    Protection(
        "proof_checklist",
        "agent_gated",
        "proof workflow requests diagnosis plus Lean evidence or an unverified label",
        "the proof and write-up workflows are followed",
        "Lean is optional and direct prose edits remain possible",
    ),
    Protection(
        "baseline_fairness",
        "advisory",
        "baseline_fairness reports resource-ratio violations",
        "the comparison logs contain parseable budget fields",
        "the tool reports a verdict but does not stop later commands",
    ),
    Protection(
        "bt_pause",
        "advisory",
        "low-strength branches emit pause suggestions by default",
        "the branch has enough comparisons",
        "automatic pausing requires an explicit environment opt-in",
    ),
    Protection(
        "cockpit_risk",
        "advisory",
        "Cockpit surfaces stale claims, failures, budgets, and interventions",
        "Cockpit reads the same workspace state database",
        "monitoring alone does not block an agent action",
    ),
)


def list_protections(level: ProtectionLevel | None = None) -> list[dict[str, str]]:
    if level is not None and level not in PROTECTION_LEVELS:
        raise ValueError(f"level must be one of {PROTECTION_LEVELS}")
    return [
        asdict(protection)
        for protection in PROTECTIONS
        if level is None or protection.level == level
    ]


__all__ = ["PROTECTION_LEVELS", "PROTECTIONS", "Protection", "list_protections"]
