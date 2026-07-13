"""Fail when a release wheel omits required runtime assets."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

REQUIRED_SUFFIXES = (
    "claudescientist/cli.py",
    "claudescientist/codex_cli.py",
    "claudescientist/codex_hooks.py",
    "claudescientist/doctor.py",
    "claudescientist/plugin_setup.py",
    "claudescientist/runtime.py",
    "cockpit/action_router.py",
    "cockpit/command_handler.py",
    "cockpit/intervention_controller.py",
    "cockpit/refresh_coordinator.py",
    "cockpit/tui.py",
    "cockpit/i18n.py",
    "cockpit/theme/cockpit.tcss",
    "memory_mcp/server.py",
    "memory_mcp/bt_simulation.py",
    "verify_mcp/server.py",
    "prove_mcp/server.py",
)


def inspect_wheel(path: Path) -> list[str]:
    """Return missing required suffixes from one wheel."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    return [
        suffix
        for suffix in REQUIRED_SUFFIXES
        if not any(name.endswith(suffix) for name in names)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)
    missing = inspect_wheel(args.wheel)
    if missing:
        parser.error("wheel is missing required assets: " + ", ".join(missing))
    print(f"wheel assets OK: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
