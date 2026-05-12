"""``python -m cockpit.export`` entrypoint.

Usage::

    uv run python -m cockpit.export <kind> <node_id>
    uv run python -m cockpit.export <kind> <node_id> --format md
    uv run python -m cockpit.export <kind> <node_id> --format md,html
    uv run python -m cockpit.export --list-kinds

The CLI is intentionally thin — it parses arguments, calls
``pipeline.generate``, and prints the resulting paths. Any
ValueError / OSError surfaces as a non-zero exit with a message on
stderr; there's no clever recovery logic.
"""

from __future__ import annotations

import argparse
import sys

from cockpit.export import FORMATS, KINDS, generate


def _parse_formats(raw: str) -> list[str]:
    out: list[str] = []
    for piece in (raw or "").split(","):
        piece = piece.strip().lower()
        if not piece:
            continue
        if piece not in FORMATS:
            raise SystemExit(
                f"error: unknown format {piece!r}; expected one of "
                f"{', '.join(sorted(FORMATS))}"
            )
        if piece not in out:
            out.append(piece)
    if not out:
        return ["md"]
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cockpit.export",
        description="Generate cockpit report files from SQLite state.",
    )
    parser.add_argument(
        "kind",
        nargs="?",
        help=f"report kind ({', '.join(sorted(KINDS))})",
    )
    parser.add_argument(
        "node_id",
        nargs="?",
        help="target mem_nodes.node_id (proposition / hypothesis / …)",
    )
    parser.add_argument(
        "--format",
        default="md",
        help="comma-separated list of formats (md, html); default: md",
    )
    parser.add_argument(
        "--list-kinds",
        action="store_true",
        help="print the supported report kinds and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_kinds:
        for kind in sorted(KINDS):
            print(kind)
        return 0
    if not args.kind or not args.node_id:
        parser.error("kind and node_id are required (or pass --list-kinds)")
        return 2

    if args.kind not in KINDS:
        print(
            f"error: unknown kind {args.kind!r}; expected one of "
            f"{', '.join(sorted(KINDS))}",
            file=sys.stderr,
        )
        return 2

    formats = _parse_formats(args.format)

    try:
        paths = generate(
            args.kind,
            args.node_id,
            formats=formats,
            generated_by="cockpit.export.cli",
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error writing report: {exc}", file=sys.stderr)
        return 1

    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
