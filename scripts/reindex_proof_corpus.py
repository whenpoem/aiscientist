#!/usr/bin/env python
"""Re-embed the proof corpus under the active embedding backend.

The corpus stores each keyword string alongside its embedding bytes plus
a (backend, model, dim) triple identifying how the embedding was made.
When that triple changes — say you switch
``RESEARCH_AGENT_EMBED_BACKEND`` from ``local`` to ``openai``, or you
upgrade ``RESEARCH_AGENT_EMBED_MODEL`` from ``all-MiniLM-L6-v2`` to
``Qwen/Qwen3-Embedding-0.6B`` — the old vectors stay in the table but
``retrieve_skeletons`` refuses to mix them with new queries. This
script re-encodes every keyword under the active configuration so
retrieval works again.

Usage::

    uv run python scripts/reindex_proof_corpus.py
    uv run python scripts/reindex_proof_corpus.py --dry-run
    uv run python scripts/reindex_proof_corpus.py --batch-size 50

The dry-run mode reports the (backend, model, dim) triples currently
present in the corpus and the active triple, but writes nothing. It is
the cheap way to confirm whether a re-index is actually needed before
paying the embedding cost.

The script is idempotent. Running it twice with the same active
configuration re-encodes the same vectors and writes the same metadata
the second time; nothing breaks. The cockpit only nudges the user
toward this script when it detects a triple mismatch on startup.
"""

from __future__ import annotations

import argparse
import sys

DEFAULT_BATCH_SIZE = 25


def _print_signatures(out, active: dict, signatures: list[dict]) -> None:
    out.write("active backend / model / dim:\n")
    out.write(
        f"  {active['backend']!r} / {active['model']!r} / dim={active['dim']}\n"
    )
    out.write("\n")
    out.write(f"corpus contains {len(signatures)} distinct triple(s):\n")
    if not signatures:
        out.write("  (corpus is empty)\n")
        return
    for sig in signatures:
        marker = " <- active" if (
            sig["embed_backend"] == active["backend"]
            and sig["embedding_model"] == active["model"]
            and sig["embed_dim"] == active["dim"]
        ) else ""
        out.write(
            f"  {sig['embed_backend']!r} / {sig['embedding_model']!r} / "
            f"dim={sig['embed_dim']:<5}  rows={sig['row_count']}{marker}\n"
        )


def run(
    *,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    out=sys.stdout,
) -> dict:
    """Programmatic entry point.

    Returns the dict produced by ``reindex_corpus()`` (or a dry-run
    summary when ``dry_run=True``). Importable from tests.
    """
    # Lazy import so --help works without the optional embedding deps.
    from prove_mcp.embedding import get_embedder
    from prove_mcp.tools.corpus import corpus_backend_signatures, reindex_corpus

    signatures = corpus_backend_signatures()

    backend = get_embedder()
    active = {
        "backend": backend.name,
        "model": backend.model_name,
        "dim": None,
    }

    if dry_run:
        active_rows = [
            sig for sig in signatures
            if (
                sig["embed_backend"] == active["backend"]
                and sig["embedding_model"] == active["model"]
            )
        ]
        distinct_dims = {int(sig["embed_dim"]) for sig in active_rows}
        if len(distinct_dims) == 1:
            active["dim"] = distinct_dims.pop()
    else:
        active["dim"] = backend.dim

    _print_signatures(out, active, signatures)
    out.write("\n")

    if dry_run:
        mismatched = [
            sig for sig in signatures
            if not (
                sig["embed_backend"] == active["backend"]
                and sig["embedding_model"] == active["model"]
                and (
                    active["dim"] is None
                    or sig["embed_dim"] == active["dim"]
                )
            )
        ]
        out.write(
            f"dry-run: {sum(sig['row_count'] for sig in mismatched)} row(s) "
            f"across {len(mismatched)} triple(s) would be re-encoded.\n"
        )
        return {
            "dry_run": True,
            "mismatched_triples": len(mismatched),
            "mismatched_rows": sum(sig["row_count"] for sig in mismatched),
            "active": active,
        }

    result = reindex_corpus(batch_size=batch_size)
    out.write(
        f"done: re-encoded {result['reindexed']} problem(s), "
        f"skipped {result['skipped']} (no keywords), "
        f"under backend={result['backend']!r} model={result['model']!r} "
        f"dim={result['dim']}\n"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report which (backend, model, dim) triples exist; write nothing",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="re-encode in batches of this size to bound embedding-backend memory",
    )
    args = parser.parse_args(argv)

    try:
        run(dry_run=args.dry_run, batch_size=max(1, args.batch_size))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
