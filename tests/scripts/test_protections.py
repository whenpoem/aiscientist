from __future__ import annotations

import pytest

from claudescientist.protections import PROTECTION_LEVELS, list_protections
from cockpit.i18n import t


def test_protection_catalog_covers_all_strength_levels() -> None:
    rows = list_protections()
    assert {row["level"] for row in rows} == set(PROTECTION_LEVELS)
    assert len({row["protection_id"] for row in rows}) == len(rows)
    assert all(row["condition"] and row["degradation"] for row in rows)


def test_protection_catalog_filters_and_validates_levels() -> None:
    enforced = list_protections("enforced")
    assert enforced
    assert {row["level"] for row in enforced} == {"enforced"}
    with pytest.raises(ValueError):
        list_protections("absolute")  # type: ignore[arg-type]


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_cockpit_help_localizes_protection_strength(lang: str) -> None:
    keys = (
        "help_protection_strength",
        "protection_enforced_help",
        "protection_agent_gated_help",
        "protection_advisory_help",
    )
    assert all(t(lang, key) != key for key in keys)
