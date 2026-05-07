#!/usr/bin/env python
"""Bootstrap the proof corpus from a JSONL seed file.

Reads ``data/proof_corpus_seed.jsonl`` (one problem per line) and ingests it
through ``prove_mcp.tools.corpus.ingest_proof_corpus``. Existing problems are
upserted by ``problem_id`` (the underlying tool already does this).

Usage::

    uv run python scripts/seed_proof_corpus.py
    uv run python scripts/seed_proof_corpus.py --input data/my_corpus.jsonl
    uv run python scripts/seed_proof_corpus.py --limit 50
    uv run python scripts/seed_proof_corpus.py --source stateval

The default embedding backend is taken from ``RESEARCH_AGENT_EMBED_BACKEND``;
in a fresh ``uv sync --extra proof`` checkout this is the local
sentence-transformers backend. Tests pin ``mock`` via tests/conftest.py.

This script is idempotent. Running it twice produces the same corpus.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "proof_corpus_seed.jsonl"
DEFAULT_SOURCE = "manual"
DEFAULT_BATCH_SIZE = 25


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{lineno}: invalid JSON ({exc.msg})"
                ) from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{lineno}: row must be a JSON object")
            yield row


def _batched(rows: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def run(
    input_path: Path | None = None,
    *,
    source: str = DEFAULT_SOURCE,
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    out=sys.stdout,
) -> dict[str, int]:
    """Programmatic entry point. Returns aggregate counts.

    Importable from tests; the CLI in ``main()`` just parses args and calls
    this function. ``input_path=None`` falls back to the bundled seed file.
    """
    # Lazy import so CLI ``--help`` works even when the prove backend is
    # not yet importable (eg before ``uv sync``).
    from prove_mcp.tools.corpus import ingest_proof_corpus

    path = Path(input_path) if input_path else DEFAULT_INPUT
    if not path.exists():
        raise FileNotFoundError(f"corpus seed file not found: {path}")

    rows: list[dict[str, Any]] = []
    for row in _iter_jsonl(path):
        rows.append(row)
        if limit is not None and len(rows) >= limit:
            break

    if not rows:
        out.write(f"no rows in {path}; nothing to ingest\n")
        return {"ingested": 0, "replaced": 0, "rows": 0}

    total_ingested = 0
    total_replaced = 0
    backend_name = ""
    for batch in _batched(rows, batch_size):
        result = ingest_proof_corpus(source=source, problems=batch)
        total_ingested += int(result.get("ingested", 0))
        total_replaced += int(result.get("replaced", 0))
        backend_name = str(result.get("backend") or backend_name)
        out.write(
            f"  batch of {len(batch):3d}: "
            f"ingested={result.get('ingested', 0)} "
            f"replaced={result.get('replaced', 0)} "
            f"backend={result.get('backend', '?')}\n"
        )

    out.write(
        f"done: {total_ingested} new, {total_replaced} replaced "
        f"(backend={backend_name or 'unknown'}, rows={len(rows)}, source={source!r})\n"
    )
    return {
        "ingested": total_ingested,
        "replaced": total_replaced,
        "rows": len(rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=f"path to JSONL seed file (default: {DEFAULT_INPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        choices=["stateval", "manual", "arxiv"],
        help="ingest source label written into prv_corpus_problems.source",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="ingest at most this many rows (useful for smoke tests)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="ingest in batches of this size to bound embedding-backend memory",
    )
    args = parser.parse_args(argv)

    try:
        run(
            input_path=args.input,
            source=args.source,
            limit=args.limit,
            batch_size=max(1, args.batch_size),
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
