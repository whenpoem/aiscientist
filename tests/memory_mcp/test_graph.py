from __future__ import annotations

import json


def test_graph_lifecycle(workspace):
  impl = workspace["memory_mcp.impl"]
  db = workspace["memory_mcp.db"]

  root = impl.propose_hypothesis("Dropout stabilizes scaling in ViT")["node_id"]
  child = impl.propose_hypothesis(
      "Per-head dropout helps more than shared dropout",
      parent_id=root,
  )["node_id"]
  evidence = impl.attach_evidence(
      child,
      "Validation accuracy improved by 0.8 points",
      "supports",
  )["evidence_id"]
  impl.mark_refuted(child, "Later run regressed", evidence_ids=[evidence])

  ancestors = impl.get_ancestors(child)
  frontier = impl.get_active_frontier()

  assert ancestors[0]["node_id"] == child
  assert ancestors[1]["node_id"] == root
  assert any(node["node_id"] == root for node in frontier)
  assert all(node["node_id"] != child for node in frontier)

  snap = impl.snapshot("post-refutation")

  con = db._connect()
  try:
    row = con.execute(
        "SELECT label, payload FROM mem_snapshots WHERE snapshot_id = ?",
        (snap["snapshot_id"],),
    ).fetchone()
  finally:
    con.close()

  payload = json.loads(row["payload"])
  assert row["label"] == "post-refutation"
  assert payload["counts"]["nodes"] == 3
  assert payload["counts"]["edges"] == 4
  assert payload["counts"]["active_frontier"] == 1
  assert payload["active_frontier"][0]["node_id"] == root
