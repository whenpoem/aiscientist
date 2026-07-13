"""Install the portable Codex plugin for one user."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .codex_cli import codex_command_prefix

DEFAULT_MARKETPLACE_SOURCE = "whenpoem/aiscientist"
DEFAULT_MARKETPLACE_NAME = "claudescientist"
DEFAULT_PLUGIN_NAME = "claudescientist"

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(command: Sequence[str], *, runner: Runner) -> dict[str, Any]:
    try:
        completed = runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "command": list(command),
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }
    return {
        "command": list(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def install_user_plugin(
    *,
    source: str = DEFAULT_MARKETPLACE_SOURCE,
    ref: str | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Install the version-matched marketplace and plugin through Codex CLI."""

    prefix = codex_command_prefix()
    if prefix is None:
        return {
            "ok": False,
            "error": "codex_not_found",
            "detail": "Install Codex CLI before using --scope user.",
            "steps": [],
        }

    selected_ref = ref or f"v{__version__}"
    marketplace_command = [*prefix, "plugin", "marketplace", "add", source]
    source_is_local = Path(source).expanduser().exists()
    applied_ref = None if source_is_local else selected_ref
    if applied_ref:
        marketplace_command.extend(["--ref", applied_ref])
    marketplace_command.append("--json")
    steps: list[dict[str, Any]] = []
    marketplace_result = _run(marketplace_command, runner=runner)
    steps.append(marketplace_result)
    if marketplace_result["returncode"] != 0:
        return {
            "ok": False,
            "error": "codex_plugin_install_failed",
            "source": source,
            "ref": applied_ref,
            "requested_ref": selected_ref,
            "steps": steps,
        }

    marketplace_name = DEFAULT_MARKETPLACE_NAME
    try:
        marketplace_payload = json.loads(marketplace_result["stdout"] or "{}")
    except json.JSONDecodeError:
        marketplace_payload = {}
    if isinstance(marketplace_payload, dict) and marketplace_payload.get(
        "marketplaceName"
    ):
        marketplace_name = str(marketplace_payload["marketplaceName"])

    plugin_selector = f"{DEFAULT_PLUGIN_NAME}@{marketplace_name}"
    plugin_command = [*prefix, "plugin", "add", plugin_selector, "--json"]
    plugin_result = _run(plugin_command, runner=runner)
    steps.append(plugin_result)
    if plugin_result["returncode"] != 0:
        return {
            "ok": False,
            "error": "codex_plugin_install_failed",
            "source": source,
            "ref": applied_ref,
            "requested_ref": selected_ref,
            "steps": steps,
        }

    return {
        "ok": True,
        "source": source,
        "ref": applied_ref,
        "requested_ref": selected_ref,
        "plugin": plugin_selector,
        "restart_required": True,
        "steps": steps,
    }


__all__ = ["install_user_plugin"]
