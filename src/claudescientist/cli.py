"""Unified command-line entrypoint used by installs and the Codex plugin."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path

from . import __version__


@contextmanager
def _workspace_context(value: str | None):
    key = "RESEARCH_AGENT_WORKSPACE"
    previous = os.environ.get(key)
    if value:
        os.environ[key] = str(Path(value).expanduser().resolve())
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _run_mcp(server: str) -> int:
    if server == "cockpit":
        from cockpit.mcp_server import main

        main()
        return 0
    modules = {
        "memory": "memory_mcp.server",
        "verify": "verify_mcp.server",
        "prove": "prove_mcp.server",
    }
    module = __import__(modules[server], fromlist=["mcp"])
    module.mcp.run(show_banner=False, log_level="ERROR")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claudescientist")
    parser.add_argument(
        "--version", action="version", version=f"claudescientist {__version__}"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    cockpit = commands.add_parser("cockpit", help="open the local research control panel")
    cockpit.add_argument("--workspace")
    cockpit.add_argument("--lang", choices=("en", "zh"))
    cockpit.add_argument("--theme")
    cockpit.add_argument("--once", action="store_true")
    cockpit.add_argument("--prune-events", type=int, metavar="N")

    doctor = commands.add_parser("doctor", help="diagnose plugin, hooks, MCPs, and workspace")
    doctor.add_argument("--workspace")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    mcp = commands.add_parser("mcp", help="run one bundled MCP server over stdio")
    mcp.add_argument("server", choices=("memory", "verify", "prove", "cockpit"))
    mcp.add_argument("--workspace")

    hook = commands.add_parser("hook", help="run one bundled lifecycle hook")
    hook.add_argument("hook_args", nargs=argparse.REMAINDER)

    setup = commands.add_parser("setup", help="configure project or user installation")
    setup.add_argument("--scope", choices=("project", "user"), default="project")
    setup.add_argument("--non-interactive", action="store_true")
    setup.add_argument("--reset", action="store_true")
    setup.add_argument("--skip-deps", action="store_true")
    setup.add_argument("--repo-root")
    setup.add_argument("--marketplace-source", default="whenpoem/aiscientist")
    setup.add_argument("--ref", dest="plugin_ref")
    setup.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _print_doctor(result: dict) -> None:
    print(f"ClaudeScientist doctor: {result['overall']}")
    for name, check in result["checks"].items():
        detail = check.get("detail") or check.get("path") or ""
        print(f"- {name}: {check['status']} {detail}".rstrip())


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "cockpit":
        forwarded: list[str] = []
        if args.lang:
            forwarded.extend(["--lang", args.lang])
        if args.theme:
            forwarded.extend(["--theme", args.theme])
        if args.once:
            forwarded.append("--once")
        if args.prune_events is not None:
            forwarded.extend(["--prune-events", str(args.prune_events)])
        from cockpit.tui import main as cockpit_main

        return cockpit_main(forwarded)
    if args.command == "doctor":
        from .doctor import run_doctor

        result = run_doctor()
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_doctor(result)
        return 1 if result["overall"] == "error" else 0
    if args.command == "mcp":
        return _run_mcp(args.server)
    if args.command == "hook":
        from .codex_hooks import main as hook_main

        return hook_main(args.hook_args)
    if args.command == "setup":
        if args.scope == "project":
            forwarded: list[str] = []
            if args.non_interactive:
                forwarded.append("--non-interactive")
            if args.reset:
                forwarded.append("--reset")
            if args.skip_deps:
                forwarded.append("--skip-deps")
            if args.repo_root:
                forwarded.extend(["--repo-root", args.repo_root])
            from .setup import main as setup_main

            return setup_main(forwarded)

        from .plugin_setup import install_user_plugin

        result = install_user_plugin(
            source=args.marketplace_source,
            ref=args.plugin_ref,
        )
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result["ok"]:
            print(
                "ClaudeScientist plugin installed. Start a new Codex task, "
                "review the hook trust prompt, then run `claudescientist doctor`."
            )
        else:
            detail = result.get("detail") or result.get("error") or "unknown error"
            print(f"ClaudeScientist plugin setup failed: {detail}")
            for step in result.get("steps", []):
                if step.get("stderr"):
                    print(step["stderr"])
        return 0 if result["ok"] else 1
    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with _workspace_context(getattr(args, "workspace", None)):
        return _dispatch(args)


if __name__ == "__main__":
    raise SystemExit(main())
