"""Command-line interface for sequestered dataset registration.

Re-exported through :mod:`claudescientist.heldout` so the documented entry
point ``python -m claudescientist.heldout register|list|inspect`` keeps
working unchanged.
"""

from __future__ import annotations

import argparse
import json

from .heldout import (
    DEFAULT_HELDOUT_BUDGET,
    inspect_dataset,
    list_datasets,
    register_dataset,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m claudescientist.heldout")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser(
        "register",
        help="Register and move a sequestered dataset.",
    )
    register_parser.add_argument("dataset")
    register_parser.add_argument("path")
    register_parser.add_argument("--budget-total", type=int, default=DEFAULT_HELDOUT_BUDGET)

    subparsers.add_parser("list", help="List registered sequestered datasets.")

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a registered sequestered dataset.",
    )
    inspect_parser.add_argument("dataset")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            result = register_dataset(
                args.dataset,
                args.path,
                budget_total=args.budget_total,
            )
        elif args.command == "list":
            result = {"ok": True, "datasets": list_datasets()}
        else:
            result = {"ok": True, **inspect_dataset(args.dataset)}
        exit_code = 0
    except KeyError:
        result = {"ok": False, "error": "unknown_dataset", "dataset": args.dataset}
        exit_code = 1
    except Exception as exc:  # pragma: no cover - defensive CLI surface
        result = {"ok": False, "error": exc.__class__.__name__, "message": str(exc)}
        exit_code = 1
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
