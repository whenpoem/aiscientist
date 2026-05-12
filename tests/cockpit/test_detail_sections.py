"""Detail pane Collapsible sections (v4.2.0a1 / A2).

Three layers of behavior to nail down:

1. ``node_detail_sections`` returns the right sections for the right node
   kinds, with the right ordering and the right ``empty`` / ``default_open``
   flags.
2. The pre-existing ``node_detail_text`` shim still produces a single
   Text object whose content covers every section. Tests built against
   the v4.1 API keep working.
3. The detail pane's persistence callback fires when the user toggles a
   section, and the new state lands in CockpitSettings.
"""

from __future__ import annotations

import pytest

from cockpit.details import (
    SECTION_KEYS,
    DetailSection,
    node_detail_sections,
    node_detail_text,
)


def test_section_keys_constant_is_ordered_tuple():
    """The pane allocates one Collapsible per key; the order matters."""
    assert isinstance(SECTION_KEYS, tuple)
    assert SECTION_KEYS[0] == "overview"
    # Overview is the only section guaranteed present for every node.
    assert "overview" in SECTION_KEYS


def test_node_detail_sections_returns_overview_for_basic_hypothesis(workspace):
    """A vanilla hypothesis should produce at minimum an overview section."""
    impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace["cockpit.data"]

    impl.propose_hypothesis("Test hypothesis")
    graph = cockpit_data.fetch_graph()
    [node_id] = list(graph.nodes.keys())

    title, sections = node_detail_sections(graph, node_id, "en")
    assert title  # short id + kind label
    keys = [s.key for s in sections]
    assert "overview" in keys


def test_node_detail_sections_drops_children_when_empty(workspace):
    """A leaf node should not get a "Children (0)" section — empty sections
    are dropped entirely rather than rendered with a dash."""
    impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace["cockpit.data"]

    impl.propose_hypothesis("Leaf hypothesis")
    graph = cockpit_data.fetch_graph()
    [node_id] = list(graph.nodes.keys())

    _, sections = node_detail_sections(graph, node_id, "en")
    keys = [s.key for s in sections]
    assert "children" not in keys


def test_node_detail_sections_includes_children_when_present(workspace):
    """A parent node should get a "Children (N)" section with N matching
    the child count."""
    impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace["cockpit.data"]

    parent = impl.propose_hypothesis("Parent")
    impl.propose_hypothesis("Child 1", parent_id=parent["node_id"])
    impl.propose_hypothesis("Child 2", parent_id=parent["node_id"])
    graph = cockpit_data.fetch_graph()

    _, sections = node_detail_sections(graph, parent["node_id"], "en")
    by_key = {s.key: s for s in sections}
    assert "children" in by_key
    # Title carries the count in the i18n template.
    assert "2" in by_key["children"].title


def test_node_detail_sections_unknown_id_returns_empty():
    """Stale node id → no sections; the pane falls back to its hint view."""

    class _StubGraph:
        def node(self, node_id):
            return None

    title, sections = node_detail_sections(_StubGraph(), "ghost", "en")
    assert title == ""
    assert sections == []


def test_node_detail_text_shim_includes_every_section_title(workspace):
    """Legacy callers using ``node_detail_text`` keep getting the full
    rendered body. The shim joins every section title + body, separated
    by blank lines, so test assertions against "Status:" still find it."""
    impl = workspace["memory_mcp.impl"]
    cockpit_data = workspace["cockpit.data"]

    parent = impl.propose_hypothesis("Parent")
    impl.propose_hypothesis("Child 1", parent_id=parent["node_id"])
    graph = cockpit_data.fetch_graph()

    _, body = node_detail_text(graph, parent["node_id"], "en")
    plain = body.plain
    assert "Status:" in plain  # from overview
    assert "Children" in plain  # children section header


def test_detail_section_with_body_helper_returns_copy():
    """The .with_body method returns a fresh frozen dataclass with the
    same key / title / flags but a new body."""
    from rich.text import Text

    original = DetailSection(
        key="x", title="X", body=Text("old"), default_open=False, empty=False
    )
    replaced = original.with_body(Text("new"))
    assert original is not replaced
    assert replaced.body.plain == "new"
    assert replaced.key == original.key
    assert replaced.default_open == original.default_open


@pytest.mark.asyncio
async def test_detail_pane_toggle_callback_fires_and_persists(workspace):
    """When the user collapses a section, the App's callback fires and
    the new state lands in ``CockpitSettings.detail_section_collapsed``."""
    from cockpit.app import CockpitApp

    impl = workspace["memory_mcp.impl"]
    impl.propose_hypothesis("Drives the detail pane")

    app = CockpitApp()
    async with app.run_test():
        # The pane has been populated by the refresh on mount.
        assert app.detail_pane is not None
        # Simulate the toggle callback directly. We don't fire a real
        # Collapsible.Toggled event because Textual's Collapsible event
        # wiring varies across versions; the contract under test is
        # that whatever the pane chooses to invoke as "user toggled
        # section X", the App persists it.
        app._on_detail_section_toggled("overview", True)
        assert app._settings.detail_section_collapsed.get("overview") is True
        # Toggling back records the new value, doesn't drop the key.
        app._on_detail_section_toggled("overview", False)
        assert app._settings.detail_section_collapsed.get("overview") is False


@pytest.mark.asyncio
async def test_detail_pane_seeds_collapsed_state_from_settings(workspace):
    """The pane reads its initial collapsed state from CockpitSettings
    on mount so a power user who collapsed "children" last session sees
    it collapsed on next launch."""
    from cockpit.app import CockpitApp
    from cockpit.settings import CockpitSettings

    impl = workspace["memory_mcp.impl"]
    parent = impl.propose_hypothesis("Parent")
    impl.propose_hypothesis("Child", parent_id=parent["node_id"])

    seeded = CockpitSettings(detail_section_collapsed={"children": True})
    app = CockpitApp(settings=seeded)
    async with app.run_test():
        # The pane's view of the persisted state mirrors what the App
        # injected on mount.
        assert app.detail_pane._collapsed_state.get("children") is True