"""Tests for scripts/seed_proof_failures.py.

The script ingests JSONL rows into mem_failures(domain='proof') with
idempotency on the (trigger, root_cause) natural key.
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
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "seed_proof_failures" in sys.modules:
        del sys.modules["seed_proof_failures"]
    return importlib.import_module("seed_proof_failures")


def _write_seed(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def test_run_inserts_rows(workspace, seed_module, tmp_path):
    seed = _write_seed(
        tmp_path / "fail.jsonl",
        [
            {
                "trigger": "Cauchy-Schwarz without finite second moment",
                "symptom": "bound asserted without integrability check",
                "root_cause": "missed E[X^2], E[Y^2] < infinity hypothesis",
                "resolution": "verify finite second moments first",
            },
            {
                "trigger": "Jensen with concave function",
                "symptom": "inequality direction reversed",
                "root_cause": "phi was concave, not convex",
                "resolution": "verify convexity or flip sign",
            },
        ],
    )
    impl = workspace["memory_mcp.impl"]
    result = seed_module.run(input_path=seed, out=io.StringIO())
    assert result == {"inserted": 2, "skipped": 0, "malformed": 0}
    rows = impl.match_signatures("Cauchy-Schwarz second moment", domain="proof")
    triggers = {r["trigger"] for r in rows}
    assert "Cauchy-Schwarz without finite second moment" in triggers


def test_run_is_idempotent(workspace, seed_module, tmp_path):
    seed = _write_seed(
        tmp_path / "fail.jsonl",
        [
            {
                "trigger": "Cauchy-Schwarz without finite second moment",
                "symptom": "bound asserted without integrability check",
                "root_cause": "missed E[X^2], E[Y^2] < infinity hypothesis",
                "resolution": "verify finite second moments first",
            }
        ],
    )
    first = seed_module.run(input_path=seed, out=io.StringIO())
    second = seed_module.run(input_path=seed, out=io.StringIO())
    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["skipped"] == 1


def test_run_skips_malformed(workspace, seed_module, tmp_path):
    seed = _write_seed(
        tmp_path / "fail.jsonl",
        [
            {
                "trigger": "valid",
                "symptom": "valid symptom",
                "root_cause": "valid",
                "resolution": "valid",
            },
            {"trigger": "", "symptom": "missing trigger", "root_cause": "x", "resolution": "y"},
            {"trigger": "no symptom", "symptom": "", "root_cause": "x", "resolution": "y"},
        ],
    )
    result = seed_module.run(input_path=seed, out=io.StringIO())
    assert result["inserted"] == 1
    assert result["malformed"] == 2


def test_run_respects_limit(workspace, seed_module, tmp_path):
    seed = _write_seed(
        tmp_path / "fail.jsonl",
        [
            {
                "trigger": f"trigger {i}",
                "symptom": f"symptom {i}",
                "root_cause": f"cause {i}",
                "resolution": f"fix {i}",
            }
            for i in range(5)
        ],
    )
    result = seed_module.run(input_path=seed, limit=2, out=io.StringIO())
    assert result["inserted"] == 2


def test_run_missing_file(workspace, seed_module, tmp_path):
    with pytest.raises(FileNotFoundError):
        seed_module.run(input_path=tmp_path / "missing.jsonl", out=io.StringIO())


def test_main_help_runs(seed_module, capsys):
    with pytest.raises(SystemExit) as exc_info:
        seed_module.main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "seed" in out.lower()
