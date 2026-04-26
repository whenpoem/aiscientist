"""Command-line entry point for the cockpit TUI."""

from __future__ import annotations

import argparse

from .app import CockpitApp, render_snapshot
from .i18n import SUPPORTED_LANGS, normalize_lang


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cockpit.tui")
    parser.add_argument("--once", action="store_true", help="render one textual snapshot and exit")
    parser.add_argument(
        "--lang",
        choices=sorted(SUPPORTED_LANGS),
        default="en",
        help="UI language",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lang = normalize_lang(args.lang)
    if args.once:
        print(render_snapshot(lang=lang))
        return 0
    CockpitApp(lang=lang).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
