"""Command-line entry point for the cockpit TUI."""

from __future__ import annotations

import argparse

from .app import CockpitApp, render_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cockpit.tui")
    parser.add_argument("--once", action="store_true", help="render one textual snapshot and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.once:
        print(render_snapshot())
        return 0
    CockpitApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
