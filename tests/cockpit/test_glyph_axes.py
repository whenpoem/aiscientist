"""Phase B regression: glyph axes are visually disjoint.

The cockpit carries four glyph axes:

- ``KIND_ICONS`` in :mod:`cockpit.i18n` — node kinds in the tree
- ``PHASE_GLYPH`` in :mod:`cockpit.phase` — current research phase
- ``FAMILY_GLYPH`` in :mod:`cockpit.activity` — activity card family
- ``SEVERITY_GLYPH`` in :mod:`cockpit.activity` — card severity

Before Phase B these axes shared glyphs accidentally (``◇`` appeared in
KIND/PHASE/FAMILY, ``▲`` in KIND/SEVERITY/FAMILY), so an activity card
rendered ``▲ ▲ branch_paused`` — same triangle twice in a row with two
different meanings. Phase B repaired this by changing PHASE/FAMILY/
SEVERITY to disjoint glyph families. These tests lock the disjointness
so future glyph edits can't silently re-introduce the conflict.

Deliberate overlaps (NOT regressions):

- ``PHASE_GLYPH["verify"]`` == ``FAMILY_GLYPH["verify"]`` (both ``✓``)
- ``PHASE_GLYPH["prove"]``  == ``FAMILY_GLYPH["prove"]``  (both ``⊢``)
- ``PHASE_GLYPH["narrate"]`` == ``FAMILY_GLYPH["narrate"]`` (both ``❝``)

These reflect a real semantic alignment: a verify-family event during
the verify phase reads as visual reinforcement. The tests below treat
them as expected overlaps rather than violations.
"""

from __future__ import annotations

from cockpit.activity import FAMILY_GLYPH, SEVERITY_GLYPH
from cockpit.i18n import KIND_ICONS, REFUTED_ICON
from cockpit.phase import PHASE_GLYPH


def _significant(glyphs: dict[str, str]) -> set[str]:
    """Return the non-whitespace glyphs from a table.

    The empty / space slot (idle phase, info severity) carries the
    "no signal here" meaning; collisions on whitespace are not visual
    conflicts.
    """
    return {g for g in glyphs.values() if g.strip()}


def test_kind_and_severity_axes_are_disjoint():
    """No kind glyph should be reused as a severity glyph.

    Severity is now a fill-density ramp (``█▓▒░`` plus space), and the
    kind axis is a geometric-shape family (``◇▲▣•★■△▴``). No overlap
    is expected.
    """
    overlap = _significant(KIND_ICONS) & _significant(SEVERITY_GLYPH)
    assert overlap == set(), (
        f"kind and severity glyphs overlap on {overlap!r}; severity must "
        "stay on the density ramp"
    )


def test_kind_and_family_axes_are_disjoint():
    """No kind glyph should appear in a family chip.

    The user originally saw ``◇`` for both ``kind=question`` and
    ``family=graph`` — confusing. Phase B moved family-graph to ``⊞``
    and family-risk to ``⚠`` to clear the conflict.
    """
    overlap = _significant(KIND_ICONS) & _significant(FAMILY_GLYPH)
    assert overlap == set(), (
        f"kind and family glyphs overlap on {overlap!r}"
    )


def test_kind_and_phase_axes_are_disjoint():
    """Phase glyphs cannot collide with kind icons.

    Phase B moved phase-explore off ◇ and phase-review off ★ to clear
    the kind-question / kind-conclusion overlaps.
    """
    overlap = _significant(KIND_ICONS) & _significant(PHASE_GLYPH)
    assert overlap == set(), (
        f"kind and phase glyphs overlap on {overlap!r}"
    )


def test_severity_and_family_axes_are_disjoint():
    """Severity and family must never share a glyph.

    The card title bar renders ``severity_glyph + family_glyph + title``
    — when these collide the user sees the same glyph twice in a row
    with two different meanings (the ``▲ ▲ branch_paused`` regression
    that motivated Phase B).
    """
    overlap = _significant(SEVERITY_GLYPH) & _significant(FAMILY_GLYPH)
    assert overlap == set(), (
        f"severity and family glyphs overlap on {overlap!r}"
    )


def test_severity_and_phase_axes_are_disjoint():
    overlap = _significant(SEVERITY_GLYPH) & _significant(PHASE_GLYPH)
    assert overlap == set(), (
        f"severity and phase glyphs overlap on {overlap!r}"
    )


def test_family_and_phase_overlap_is_only_intentional_pairs():
    """Family ↔ phase overlap is allowed *only* for the semantically
    aligned trio: verify, prove, narrate."""
    overlap = _significant(FAMILY_GLYPH) & _significant(PHASE_GLYPH)
    expected = {
        FAMILY_GLYPH["verify"],
        FAMILY_GLYPH["prove"],
        FAMILY_GLYPH["narrate"],
    }
    unexpected = overlap - expected
    assert unexpected == set(), (
        f"unexpected family/phase glyph overlap on {unexpected!r}; "
        "only verify/prove/narrate may share between axes"
    )


def test_refuted_icon_distinct_from_all_axes():
    """``✗`` is the universal "dead node" marker — it must not appear
    in any other axis or the user can't trust it."""
    refuted = {REFUTED_ICON}
    assert refuted & _significant(KIND_ICONS) == set()
    assert refuted & _significant(PHASE_GLYPH) == set()
    assert refuted & _significant(FAMILY_GLYPH) == set()
    assert refuted & _significant(SEVERITY_GLYPH) == set()


def test_all_axis_glyphs_are_single_cell():
    """Every glyph across every axis must be one monospaced cell.

    Multi-cell glyphs (CJK ideographs, emoji ZWJ sequences) would
    break the activity-card title alignment and the tree-pane
    prefix column. The set excludes empty / space slots which are
    legitimately 1-cell whitespace.
    """
    for table_name, table in (
        ("KIND_ICONS", KIND_ICONS),
        ("PHASE_GLYPH", PHASE_GLYPH),
        ("FAMILY_GLYPH", FAMILY_GLYPH),
        ("SEVERITY_GLYPH", SEVERITY_GLYPH),
    ):
        for key, glyph in table.items():
            assert len(glyph) == 1, (
                f"{table_name}[{key!r}] = {glyph!r} is not a single cell"
            )
