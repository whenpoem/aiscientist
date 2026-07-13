"""Codex hook adapter for the existing ClaudeScientist hook scripts.

Claude Code and Codex use very similar lifecycle events, but their hook payload
field names are not guaranteed to be identical. This wrapper normalizes common
Codex shapes into the JSON contract consumed by the existing scripts under
``.claude/hooks`` and then runs that script unchanged.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import runpy
import sys
from pathlib import Path
from typing import Any

from .runtime import project_root

_ALLOWED_HOOKS = {
    "destructive_bash_guard",
    "intervention_pump",
    "leakage_guard",
    "provenance_log",
    "stop_flush",
}
_PRETOOL_SAFETY_HOOKS = {"destructive_bash_guard", "leakage_guard"}

_BASH_LIKE_TOOLS = {
    "bash",
    "shell",
    "exec",
    "exec_command",
    "functions.exec_command",
}

_STDIN_BOM_PREFIXES = ("\ufeff", "\u00ef\u00bb\u00bf")
_POWERSHELL_MISDECODED_JSON_OBJECT_PREFIX = "\u9518\u7e36"


def normalize_payload(payload: dict[str, Any], *, event_name: str | None = None) -> dict[str, Any]:
    """Normalize likely Codex hook payload keys to the Claude hook contract."""

    out = dict(payload)
    hook_event_name = (
        out.get("hook_event_name")
        or out.get("hookEventName")
        or out.get("event_name")
        or out.get("eventName")
        or event_name
    )
    if hook_event_name:
        out["hook_event_name"] = str(hook_event_name)

    tool_name = (
        out.get("tool_name")
        or out.get("toolName")
        or out.get("tool")
        or out.get("name")
        or out.get("matcher")
    )
    if tool_name:
        tool_name_text = str(tool_name)
        if tool_name_text.lower() in _BASH_LIKE_TOOLS:
            tool_name_text = "Bash"
        out["tool_name"] = tool_name_text

    tool_input = (
        out.get("tool_input")
        or out.get("toolInput")
        or out.get("input")
        or out.get("arguments")
        or out.get("args")
        or {}
    )
    if isinstance(tool_input, dict):
        tool_input = dict(tool_input)
        if "command" not in tool_input:
            for key in ("cmd", "command_string", "shell_command"):
                if key in tool_input:
                    tool_input["command"] = tool_input[key]
                    break
        if "content" not in tool_input:
            for key in ("patch", "text", "body"):
                if key in tool_input:
                    tool_input["content"] = tool_input[key]
                    break
        if "file_path" not in tool_input and "path" not in tool_input:
            for key in ("file", "target_file", "target"):
                if key in tool_input:
                    tool_input["file_path"] = tool_input[key]
                    break
    out["tool_input"] = tool_input

    if "tool_output" not in out:
        for key in ("toolOutput", "tool_response", "toolResponse", "output", "result"):
            if key in out:
                out["tool_output"] = out[key]
                break
    return out


def _hook_path(hook_name: str) -> Path:
    if hook_name not in _ALLOWED_HOOKS:
        raise SystemExit(f"unknown hook {hook_name!r}")
    plugin_root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        plugin_path = Path(plugin_root) / ".claude" / "hooks" / f"{hook_name}.py"
        if plugin_path.is_file():
            return plugin_path
    root = project_root()
    if root is None:
        raise SystemExit("could not locate claudescientist repo root")
    path = root / ".claude" / "hooks" / f"{hook_name}.py"
    if not path.exists():
        raise SystemExit(f"hook script missing: {path}")
    return path


def run_hook(hook_name: str, payload: dict[str, Any], *, event_name: str | None = None) -> None:
    """Run a checked-in hook script with normalized stdin."""

    normalized = normalize_payload(payload, event_name=event_name)
    old_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(normalized))
        runpy.run_path(str(_hook_path(hook_name)), run_name="__main__")
    finally:
        sys.stdin = old_stdin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m claudescientist.codex_hooks",
        description="Run a ClaudeScientist hook from Codex lifecycle events.",
    )
    parser.add_argument("hook_name", choices=sorted(_ALLOWED_HOOKS))
    parser.add_argument("--event", default=None, help="fallback hook event name")
    return parser


def _clean_json_stdin(raw: str) -> str:
    # Some Windows PowerShell launch paths decode UTF-8 input as GBK with
    # surrogateescape. Reverse that lossless mojibake before parsing JSON.
    if any(0xDC80 <= ord(char) <= 0xDCFF for char in raw):
        try:
            raw = raw.encode("gbk", errors="surrogateescape").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    # Windows PowerShell can misdecode a UTF-8 BOM plus "{" as two codepoints.
    if raw.startswith(_POWERSHELL_MISDECODED_JSON_OBJECT_PREFIX):
        return "{" + raw[len(_POWERSHELL_MISDECODED_JSON_OBJECT_PREFIX) :]
    for prefix in _STDIN_BOM_PREFIXES:
        if raw.startswith(prefix):
            return raw[len(prefix) :]
    return raw


def _deny_invalid_payload(
    hook_name: str,
    error: json.JSONDecodeError | None = None,
) -> None:
    position = error.pos if error is not None else 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"{hook_name} received an invalid hook payload; refusing "
                        "the tool call so safety checks cannot be bypassed. "
                        f"Payload error position: {position}."
                    ),
                }
            }
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_payload = _clean_json_stdin(sys.stdin.read())
    try:
        payload = json.loads(raw_payload or "{}")
    except json.JSONDecodeError as exc:
        if args.hook_name in _PRETOOL_SAFETY_HOOKS:
            _deny_invalid_payload(args.hook_name, exc)
            return 0
        return 1
    if not isinstance(payload, dict):
        if args.hook_name in _PRETOOL_SAFETY_HOOKS:
            _deny_invalid_payload(args.hook_name)
            return 0
        return 1
    run_hook(args.hook_name, payload, event_name=args.event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
