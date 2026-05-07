#!/usr/bin/env python
"""Bootstrap the proof-domain failure ledger from a JSONL seed file.

Reads ``data/proof_failure_seed.jsonl`` (one failure per line) and inserts each
row into ``mem_failures(domain='proof')`` via
``memory_mcp.tools.failures.record_failure``. Each row should contain the four
fields ``trigger``, ``symptom``, ``root_cause``, ``resolution``.

Usage::

    uv run python scripts/seed_proof_failures.py
    uv run python scripts/seed_proof_failures.py --input data/extra_failures.jsonl
    uv run python scripts/seed_proof_failures.py --limit 20

This script is idempotent on the natural key ``(trigger, root_cause)`` --
re-running it does not double-insert. The probe runs with a direct sqlite3
read against the active state DB; no FTS needed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "proof_failure_seed.jsonl"


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


def _validate_failure(row: dict[str, Any], lineno: int, path: Path) -> tuple[str, str, str, str]:
    trigger = (row.get("trigger") or "").strip()
    symptom = (row.get("symptom") or "").strip()
    root_cause = (row.get("root_cause") or "").strip()
    resolution = (row.get("resolution") or "").strip()
    if not trigger:
        raise ValueError(f"{path}:{lineno}: row missing 'trigger'")
    if not symptom:
        raise ValueError(f"{path}:{lineno}: row missing 'symptom'")
    return trigger, symptom, root_cause, resolution


def _existing_keys(state_db: Path) -> set[tuple[str, str]]:
    """Return the set of (trigger, root_cause) tuples already recorded with
    domain='proof'. Used to enforce idempotency without touching FTS."""
    if not state_db.exists():
        return set()
    con = sqlite3.connect(str(state_db), timeout=2.0)
    try:
        rows = con.execute(
            "SELECT trigger, root_cause FROM mem_failures WHERE domain = 'proof'"
        ).fetchall()
        return {(str(r[0] or ""), str(r[1] or "")) for r in rows}
    except sqlite3.OperationalError:
        return set()
    finally:
        con.close()


def run(
    input_path: Path | None = None,
    *,
    limit: int | None = None,
    out=sys.stdout,
) -> dict[str, int]:
    """Programmatic entry point. Returns aggregate counts.

    Importable from tests; the CLI in ``main()`` just parses args and calls
    this function. ``input_path=None`` falls back to the bundled seed file.
    """
    # Lazy import so CLI ``--help`` works even when the runtime is not yet
    # importable (eg before ``uv sync``).
    from claudescientist.runtime import state_db_path
    from memory_mcp.tools.failures import record_failure

    path = Path(input_path) if input_path else DEFAULT_INPUT
    if not path.exists():
        raise FileNotFoundError(f"failure seed file not found: {path}")

    seen = _existing_keys(state_db_path())
    inserted = 0
    skipped = 0
    failures = 0

    for lineno, row in enumerate(_iter_jsonl(path), 1):
        if limit is not None and inserted + skipped >= limit:
            break
        try:
            trigger, symptom, root_cause, resolution = _validate_failure(row, lineno, path)
        except ValueError as exc:
            out.write(f"  skip line {lineno}: {exc}\n")
            failures += 1
            continue
        key = (trigger, root_cause)
        if key in seen:
            skipped += 1
            continue
        record_failure(
            trigger=trigger,
            symptom=symptom,
            root_cause=root_cause,
            resolution=resolution,
            domain="proof",
        )
        seen.add(key)
        inserted += 1

    out.write(
        f"done: {inserted} inserted, {skipped} already present, "
        f"{failures} malformed (input={path.name})\n"
    )
    return {"inserted": inserted, "skipped": skipped, "malformed": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=f"path to JSONL seed file (default: {DEFAULT_INPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="ingest at most this many rows (useful for smoke tests)",
    )
    args = parser.parse_args(argv)

    try:
        run(input_path=args.input, limit=args.limit)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
