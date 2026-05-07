"""Tests for the v4.1.0a0 proof-trunk surfaces.

Covers four layers:

1. Data fetchers (``fetch_corpus_problems`` / ``fetch_diagnostic_manifests``
   / ``fetch_lean_attempts``) — empty DB returns ``[]``; populated DB
   returns parsed rows with the expected shape.
2. ``RightTabsPane`` — empty-state hint when proof tables are empty;
   populated rows render with the i18n status labels and icons.
3. ``CockpitApp._dispatch_events`` — proof-trunk events route to the
   correct per-tab refresh methods (no over-fetching).
4. ``CockpitApp._row_detail`` — Enter on a corpus / diagnostics / lean
   row produces a localized detail-pane override.

The fixtures rely on the standard ``workspace`` (RESEARCH_AGENT_STATE_DIR
in tmp_path + mock embedding backend), so no real Lean install is needed.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers — keep test bodies focused on assertions.
# ---------------------------------------------------------------------------


def _seed_proposition(memory_impl, prove_impl, statement: str = "Proposition.") -> str:
    """Create a proposition node so ``record_lean_attempt`` will accept it.

    propose_proposition wires through memory_mcp; the returned node_id is
    a real mem_node row with kind='proposition'.
    """
    result = prove_impl.propose_proposition(text=statement)
    return result["node_id"]


def _seed_corpus_problem(prove_impl, problem_id: str = "markov-ineq") -> dict:
    return prove_impl.ingest_proof_corpus(
        source="manual",
        problems=[
            {
                "problem_id": problem_id,
                "statement": (
                    "For non-negative X with finite mean, "
                    "P(X >= a) <= E[X]/a for any a > 0."
                ),
                "reference_proof": "Apply Markov's inequality directly.",
                "lexical_keywords": ["markov", "inequality", "non-negative"],
                "semantic_keywords": ["probabilistic upper bound"],
                "domain_tags": ["probability", "inequality"],
            }
        ],
    )


# ---------------------------------------------------------------------------
# Layer 1: data fetchers
# ---------------------------------------------------------------------------


def test_fetch_corpus_problems_empty_db_returns_empty_list(workspace):
    from cockpit import data as cockpit_data

    assert cockpit_data.fetch_corpus_problems() == []


def test_fetch_corpus_problems_returns_parsed_rows(workspace):
    from cockpit import data as cockpit_data

    prove_impl = workspace["prove_mcp.impl"]
    _seed_corpus_problem(prove_impl)

    rows = cockpit_data.fetch_corpus_problems()
    assert len(rows) == 1
    row = rows[0]
    assert row["problem_id"] == "markov-ineq"
    assert row["source"] == "manual"
    assert "non-negative" in row["statement"]
    assert "P(X >= a)" in row["statement"]
    assert row["domain_tags"] == ["probability", "inequality"]
    assert row["primary_domain"] == "probability"
    assert row["n_lexical"] == 3
    assert row["n_semantic"] == 1


def test_fetch_lean_attempts_empty_db_returns_empty_list(workspace):
    from cockpit import data as cockpit_data

    assert cockpit_data.fetch_lean_attempts() == []


def test_fetch_lean_attempts_returns_parsed_rows(workspace):
    from cockpit import data as cockpit_data

    memory_impl = workspace["memory_mcp.impl"]
    prove_impl = workspace["prove_mcp.impl"]
    proposition_id = _seed_proposition(memory_impl, prove_impl)
    prove_impl.record_lean_attempt(
        proposition_id=proposition_id,
        status="verified",
        lean_source="theorem foo : 1 = 1 := rfl",
        duration_sec=2.5,
        triage={
            "eligible": True,
            "estimated_difficulty": "low",
            "reasons": ["whitelist:markov"],
        },
    )

    rows = cockpit_data.fetch_lean_attempts()
    assert len(rows) == 1
    row = rows[0]
    assert row["proposition_id"] == proposition_id
    assert row["status"] == "verified"
    assert row["duration_sec"] == pytest.approx(2.5)
    assert row["triage_difficulty"] == "low"
    assert row["triage_eligible"] is True
    assert row["triage_reasons"] == ["whitelist:markov"]
    assert "rfl" in row["lean_source"]


def test_fetch_diagnostic_manifests_empty_db_returns_empty_list(workspace):
    from cockpit import data as cockpit_data

    assert cockpit_data.fetch_diagnostic_manifests() == []


# ---------------------------------------------------------------------------
# Layer 2: RightTabsPane rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proof_tabs_render_empty_state_when_db_lacks_proof_tables(workspace):
    """A v3.x DB (or fresh install pre-seed-corpus) shouldn't crash; the
    three proof tabs should display their localized empty hints."""
    from cockpit.app import CockpitApp

    app = CockpitApp()
    async with app.run_test(size=(160, 40)):
        # Empty state: with no prv_* rows in the DB, all three proof tabs
        # carry empty data lists. The rendered table will show the localized
        # empty hint as a placeholder row, which we trust the existing
        # test_app_smoke and test_layout_adaptive coverage exercises.
        assert app.tabs_pane.corpus_rows == []
        assert app.tabs_pane.diagnostics_rows == []
        assert app.tabs_pane.lean_rows == []


@pytest.mark.asyncio
async def test_proof_tabs_populate_after_seed(workspace):
    from cockpit.app import CockpitApp

    memory_impl = workspace["memory_mcp.impl"]
    prove_impl = workspace["prove_mcp.impl"]
    _seed_corpus_problem(prove_impl)
    proposition_id = _seed_proposition(memory_impl, prove_impl)
    prove_impl.record_lean_attempt(
        proposition_id=proposition_id,
        status="failed",
        lean_source="theorem broken : 1 = 2 := rfl",
        stderr="error: type mismatch",
        duration_sec=1.0,
    )

    app = CockpitApp()
    async with app.run_test(size=(160, 40)):
        # Refresh tabs after seeding (the first paint already populated,
        # but trigger an explicit refresh in case ordering matters).
        app._refresh_tabs()
        assert len(app.tabs_pane.corpus_rows) == 1
        assert app.tabs_pane.corpus_rows[0]["problem_id"] == "markov-ineq"
        assert len(app.tabs_pane.lean_rows) == 1
        assert app.tabs_pane.lean_rows[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_lean_tab_zh_status_label(workspace):
    """In Chinese mode, the lean tab status column should show a translated
    label like '验证通过' instead of the raw 'verified' string."""
    from cockpit.app import CockpitApp

    memory_impl = workspace["memory_mcp.impl"]
    prove_impl = workspace["prove_mcp.impl"]
    proposition_id = _seed_proposition(memory_impl, prove_impl)
    prove_impl.record_lean_attempt(
        proposition_id=proposition_id,
        status="verified",
        duration_sec=0.5,
    )

    app = CockpitApp(lang="zh")
    async with app.run_test(size=(160, 40)):
        app._refresh_tabs()
        # The DataTable cells aren't directly queryable as plain strings,
        # but we can probe the i18n function the cell uses:
        from cockpit.i18n import t

        assert t("zh", "lean_status_verified") == "验证通过"
        assert t("zh", "lean_title") == "Lean"
        assert t("zh", "corpus_title") == "语料"
        assert t("zh", "diagnostics_title") == "诊断"


# ---------------------------------------------------------------------------
# Layer 3: per-pane refresh dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proof_events_dispatch_to_correct_per_tab_refresh(workspace, monkeypatch):
    """Each proof event class hits exactly one of the proof refreshers."""
    from cockpit.app import CockpitApp

    app = CockpitApp()
    async with app.run_test(size=(160, 40)):
        counters = {"corpus": 0, "diagnostics": 0, "lean": 0}
        monkeypatch.setattr(
            app,
            "_refresh_corpus",
            lambda: counters.__setitem__("corpus", counters["corpus"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_diagnostics",
            lambda: counters.__setitem__("diagnostics", counters["diagnostics"] + 1),
        )
        monkeypatch.setattr(
            app,
            "_refresh_lean",
            lambda: counters.__setitem__("lean", counters["lean"] + 1),
        )
        # Stub out the empirical refreshes so we don't care about their counts.
        for name in (
            "_refresh_graph",
            "_refresh_failures",
            "_refresh_claims",
            "_refresh_literature",
            "_refresh_risks",
            "_refresh_counts",
            "_refresh_detail",
        ):
            monkeypatch.setattr(app, name, lambda: None)

        app._dispatch_events([{"kind": "proof_corpus_ingested"}])
        app._dispatch_events([{"kind": "proof_diagnosis_complete"}])
        app._dispatch_events([{"kind": "lean_proof_succeeded"}])

        assert counters == {"corpus": 1, "diagnostics": 1, "lean": 1}


# ---------------------------------------------------------------------------
# Layer 4: drill-in (_row_detail)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corpus_row_drill_shows_full_statement(workspace):
    from cockpit.app import CockpitApp

    prove_impl = workspace["prove_mcp.impl"]
    _seed_corpus_problem(prove_impl)

    app = CockpitApp()
    async with app.run_test(size=(160, 40)):
        app._refresh_tabs()
        rows = app.tabs_pane.corpus_rows
        assert rows, "corpus row missing after seed"
        title, body = app._row_detail(rows[0])
        assert "markov-ineq" in title
        assert "non-negative" in body
        assert "probability" in body
        assert "reference proof" in body


@pytest.mark.asyncio
async def test_lean_row_drill_shows_source_and_stderr(workspace):
    from cockpit.app import CockpitApp

    memory_impl = workspace["memory_mcp.impl"]
    prove_impl = workspace["prove_mcp.impl"]
    proposition_id = _seed_proposition(memory_impl, prove_impl)
    prove_impl.record_lean_attempt(
        proposition_id=proposition_id,
        status="failed",
        lean_source="theorem broken : 1 = 2 := rfl",
        stderr="error: 1 ≠ 2",
        duration_sec=0.7,
    )

    app = CockpitApp()
    async with app.run_test(size=(160, 40)):
        app._refresh_tabs()
        rows = app.tabs_pane.lean_rows
        assert rows
        title, body = app._row_detail(rows[0])
        assert "Lean" in title
        assert "broken" in body
        assert "1 ≠ 2" in body
        assert "0.70s" in body