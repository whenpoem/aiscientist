"""mem_nodes.kind extension for proof trunk (P1 / ADR 0008).

The CHECK constraint accepts proposition / proof_skeleton / proof_snippet
in addition to the empirical kinds. v3.0 callers see no behaviour change;
new callers can write proof-trunk node kinds via raw INSERT (P2+ adds
ergonomic constructors in prove_mcp).

get_active_frontier surfaces propositions alongside questions and
hypotheses so the main model treats them as peer planning targets.
Skeletons and snippets are intentionally excluded from the frontier;
they are too granular for that view.
"""

from __future__ import annotations

import sqlite3

import pytest


def _insert_node(con, node_id: str, kind: str, text: str) -> None:
    con.execute(
        """
        INSERT INTO mem_nodes(node_id, kind, text, state, created_by, parent_id)
        VALUES(?,?,?,?,?,?)
        """,
        (node_id, kind, text, "active", "test", None),
    )


def test_mem_nodes_accepts_proof_kinds(workspace):
    db = workspace["memory_mcp.db"]

    con = db._connect()
    try:
        _insert_node(con, "prop_t1", "proposition", "E[X] = mu for iid samples")
        _insert_node(con, "psk_t1", "proof_skeleton", "use linearity of expectation")
        _insert_node(con, "psnp_t1", "proof_snippet", "by definition E[X] = ...")
        rows = con.execute(
            """
            SELECT node_id, kind FROM mem_nodes
            WHERE node_id IN ('prop_t1','psk_t1','psnp_t1')
            ORDER BY node_id
            """
        ).fetchall()
    finally:
        con.close()

    by_id = {row["node_id"]: row["kind"] for row in rows}
    assert by_id == {
        "prop_t1": "proposition",
        "psk_t1": "proof_skeleton",
        "psnp_t1": "proof_snippet",
    }


def test_mem_nodes_still_rejects_unknown_kind(workspace):
    db = workspace["memory_mcp.db"]

    con = db._connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_node(con, "bad_t1", "gibberish_kind", "should be rejected")
    finally:
        con.close()


def test_get_active_frontier_includes_proposition(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    impl.propose_hypothesis("dropout helps small data")
    con = db._connect()
    try:
        _insert_node(
            con,
            "prop_front",
            "proposition",
            "dropout is approximate Bayesian inference",
        )
    finally:
        con.close()

    frontier = impl.get_active_frontier()
    kinds = {row["kind"] for row in frontier}
    assert "hypothesis" in kinds
    assert "proposition" in kinds


def test_get_active_frontier_excludes_proof_snippets(workspace):
    impl = workspace["memory_mcp.impl"]
    db = workspace["memory_mcp.db"]

    con = db._connect()
    try:
        _insert_node(con, "prop_x", "proposition", "central proposition")
        _insert_node(con, "psk_x", "proof_skeleton", "skeleton")
        _insert_node(con, "psnp_x", "proof_snippet", "snippet")
    finally:
        con.close()

    frontier = impl.get_active_frontier()
    ids = {row["node_id"] for row in frontier}
    assert "prop_x" in ids
    assert "psk_x" not in ids
    assert "psnp_x" not in ids
