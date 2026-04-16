from __future__ import annotations


def test_ingest_and_query_literature(workspace):
  impl = workspace["memory_mcp.impl"]

  impl.ingest_paper(
      "arxiv:1234.5678",
      "arxiv",
      {
          "title": "Dropout Scaling in Vision Transformers",
          "authors": ["Ada Lovelace", "Grace Hopper"],
          "year": 2026,
          "venue": "arXiv",
          "problem": "Understand how dropout changes optimization and generalization in vision transformers.",
          "method": "Benchmark head-wise and layer-wise dropout schedules across ViT sizes.",
          "claimed_results": "Head-wise dropout improves top-1 accuracy by 0.7 on ImageNet-1k.",
          "assumptions": "ImageNet-scale supervised training.",
          "limitations": "No low-data regime study.",
          "trust_level": 0.4,
          "raw_abstract": "We study dropout scaling laws for ViTs.",
      },
  )

  rows = impl.query_literature("vision transformer dropout scaling", k=3)
  baselines = impl.find_baselines_for("head-wise dropout for ViTs", k=3)

  assert rows[0]["paper_id"] == "arxiv:1234.5678"
  assert baselines[0]["paper_id"] == "arxiv:1234.5678"

