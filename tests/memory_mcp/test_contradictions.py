from __future__ import annotations

import json


def test_find_contradictions_reports_explicit_edges_and_mixed_evidence(workspace):
  impl = workspace["memory_mcp.impl"]
  db = workspace["memory_mcp.db"]

  first = impl.propose_hypothesis("Depth helps at fixed compute")["node_id"]
  second = impl.propose_hypothesis("Width helps more than depth at fixed compute")["node_id"]
  target = impl.propose_hypothesis("Head-wise dropout is robust")["node_id"]
  impl.attach_evidence(target, "Run A improved by 0.8", "supports")
  impl.attach_evidence(target, "Run B regressed by 1.1", "refutes")

  con = db._connect()
  try:
    con.execute(
        "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
        (first, second, "contradicts", "Both claims cannot be true under the same budget."),
    )
  finally:
    con.close()

  contradictions = impl.find_contradictions()

  explicit = next(item for item in contradictions if item["type"] == "explicit_edge")
  mixed = next(item for item in contradictions if item["type"] == "evidence_conflict")

  assert explicit["src_id"] == first
  assert explicit["dst_id"] == second
  assert mixed["node_id"] == target
  assert mixed["support_count"] == 1
  assert mixed["refute_count"] == 1
  assert {item["relation"] for item in mixed["evidence"]} == {"supports", "refutes"}


def test_snapshot_persists_contradiction_summary(workspace):
  impl = workspace["memory_mcp.impl"]
  db = workspace["memory_mcp.db"]

  node_id = impl.propose_hypothesis("Token pruning helps latency")["node_id"]
  impl.attach_evidence(node_id, "Latency dropped by 12 percent", "supports")
  impl.attach_evidence(node_id, "Accuracy collapsed in the long-context run", "refutes")
  snap = impl.snapshot("with-conflict")

  con = db._connect()
  try:
    row = con.execute(
        "SELECT payload FROM mem_snapshots WHERE snapshot_id = ?",
        (snap["snapshot_id"],),
    ).fetchone()
  finally:
    con.close()

  payload = json.loads(row["payload"])
  assert payload["counts"]["contradictions"] == 1
  assert payload["contradictions"][0]["type"] == "evidence_conflict"
  assert payload["contradictions"][0]["node_id"] == node_id
