"""Command-line entry point for the cockpit TUI."""

from __future__ import annotations

import argparse

from .app import CockpitApp, render_snapshot
from .i18n import SUPPORTED_LANGS, normalize_lang
from .theme import theme_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cockpit.tui")
    parser.add_argument("--once", action="store_true", help="render one textual snapshot and exit")
    parser.add_argument(
        "--lang",
        choices=sorted(SUPPORTED_LANGS),
        default=None,
        help="UI language (overrides saved settings)",
    )
    parser.add_argument(
        "--theme",
        choices=theme_names(),
        default=None,
        help="visual theme (overrides saved settings)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # When --lang is omitted, fall back to "en" only for the headless --once
    # snapshot (which doesn't have access to settings persistence). For the
    # interactive path we pass None so saved settings win.
    if args.once:
        snapshot_lang = normalize_lang(args.lang or "en")
        print(render_snapshot(lang=snapshot_lang))
        return 0
    CockpitApp(lang=args.lang, theme=args.theme).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
