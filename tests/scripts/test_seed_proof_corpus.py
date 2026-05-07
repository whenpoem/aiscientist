"""Tests for scripts/seed_proof_corpus.py.

The script ingests JSONL rows into prv_corpus_problems via the production
ingest tool. Tests use the workspace fixture so the underlying SQLite is
isolated to tmp_path and the embedding backend is pinned to ``mock`` (per
tests/conftest.py).
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def seed_module(workspace):
    """Import scripts/seed_proof_corpus.py freshly inside the fixture's
    isolated state directory. The module imports prove_mcp lazily inside
    ``run()``, so the freshly bootstrapped DB is what gets touched."""
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "seed_proof_corpus" in sys.modules:
        del sys.modules["seed_proof_corpus"]
    return importlib.import_module("seed_proof_corpus")


def _write_seed(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def test_run_ingests_rows(workspace, seed_module, tmp_path):
    seed = _write_seed(
        tmp_path / "seed.jsonl",
        [
            {
                "problem_id": "p1",
                "statement": "Markov bound for non-negative X.",
                "lexical_keywords": ["markov"],
                "semantic_keywords": ["non-negative bound"],
            },
            {
                "problem_id": "p2",
                "statement": "Chebyshev bound from variance.",
                "lexical_keywords": ["chebyshev"],
                "semantic_keywords": ["variance bound"],
            },
        ],
    )
    out = io.StringIO()
    result = seed_module.run(input_path=seed, source="manual", out=out)
    assert result == {"ingested": 2, "replaced": 0, "rows": 2}
    impl = workspace["prove_mcp.impl"]
    listed = impl.list_corpus()
    pids = {row["problem_id"] for row in listed}
    assert pids == {"p1", "p2"}


def test_run_is_idempotent(workspace, seed_module, tmp_path):
    seed = _write_seed(
        tmp_path / "seed.jsonl",
        [
            {
                "problem_id": "p1",
                "statement": "Markov bound for non-negative X.",
                "lexical_keywords": ["markov"],
            }
        ],
    )
    seed_module.run(input_path=seed, source="manual", out=io.StringIO())
    second = seed_module.run(input_path=seed, source="manual", out=io.StringIO())
    assert second["ingested"] == 0
    assert second["replaced"] == 1


def test_run_respects_limit(workspace, seed_module, tmp_path):
    seed = _write_seed(
        tmp_path / "seed.jsonl",
        [
            {
                "problem_id": f"p{i}",
                "statement": f"Statement number {i}.",
                "lexical_keywords": [f"kw{i}"],
            }
            for i in range(5)
        ],
    )
    result = seed_module.run(
        input_path=seed, source="manual", limit=2, out=io.StringIO()
    )
    assert result == {"ingested": 2, "replaced": 0, "rows": 2}


def test_run_skips_blank_and_comment_lines(workspace, seed_module, tmp_path):
    path = tmp_path / "seed.jsonl"
    path.write_text(
        "\n".join(
            [
                "# top comment",
                "",
                json.dumps(
                    {
                        "problem_id": "p1",
                        "statement": "Statement.",
                        "lexical_keywords": ["kw"],
                    }
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    result = seed_module.run(input_path=path, source="manual", out=io.StringIO())
    assert result["ingested"] == 1


def test_run_missing_file_raises(workspace, seed_module, tmp_path):
    missing = tmp_path / "does_not_exist.jsonl"
    with pytest.raises(FileNotFoundError):
        seed_module.run(input_path=missing, source="manual", out=io.StringIO())


def test_main_help_runs(seed_module, capsys):
    with pytest.raises(SystemExit) as exc_info:
        seed_module.main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr().out
    assert "seed" in captured.lower()


def test_run_invalid_json_raises(workspace, seed_module, tmp_path):
    path = tmp_path / "seed.jsonl"
    path.write_text("{this is not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        seed_module.run(input_path=path, source="manual", out=io.StringIO())
