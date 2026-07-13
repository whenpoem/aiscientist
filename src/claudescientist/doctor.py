"""Installation and workspace diagnostics for ClaudeScientist."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from .codex_cli import codex_command_prefix, codex_home
from .runtime import state_db_path, workspace_root

CORE_IMPORTS = (
    "memory_mcp.server",
    "verify_mcp.server",
    "prove_mcp.server",
    "cockpit.mcp_server",
    "cockpit.tui",
)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _codex_plugin_status() -> dict[str, Any]:
    prefix = codex_command_prefix()
    if prefix is None:
        return {"available": False, "installed": False, "enabled": False}
    try:
        completed = subprocess.run(
            [*prefix, "plugin", "list", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": True,
            "installed": False,
            "enabled": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    if completed.returncode != 0:
        return {
            "available": True,
            "installed": False,
            "enabled": False,
            "detail": completed.stderr.strip() or f"exit code {completed.returncode}",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "available": True,
            "installed": False,
            "enabled": False,
            "detail": f"invalid `codex plugin list --json` output: {exc}",
        }
    installed = payload.get("installed", []) if isinstance(payload, dict) else []
    matching = [
        entry
        for entry in installed
        if isinstance(entry, dict)
        and (
            str(entry.get("name", "")).lower() == "claudescientist"
            or str(entry.get("pluginId", "")).lower().startswith("claudescientist@")
        )
    ]
    return {
        "available": True,
        "installed": any(bool(entry.get("installed", True)) for entry in matching),
        "enabled": any(bool(entry.get("enabled")) for entry in matching),
        "entries": [str(entry.get("pluginId", entry.get("name", ""))) for entry in matching],
        "versions": sorted(
            {str(entry["version"]) for entry in matching if entry.get("version")}
        ),
    }


def _project_hook_config(root: Path) -> bool:
    codex_config = root / ".codex" / "config.toml"
    claude_config = root / ".claude" / "settings.json"
    if codex_config.is_file():
        text = codex_config.read_text(encoding="utf-8", errors="ignore")
        if "intervention_pump" in text:
            return True
    if claude_config.is_file():
        text = claude_config.read_text(encoding="utf-8", errors="ignore")
        if "intervention_pump" in text:
            return True
    return False


def _trusted_claudescientist_hooks() -> bool:
    config = _read_toml(codex_home() / "config.toml")
    state = config.get("hooks", {}).get("state", {})
    if not isinstance(state, dict):
        return False
    return any(
        "claudescientist" in str(source).lower()
        and isinstance(value, dict)
        and bool(value.get("trusted_hash"))
        for source, value in state.items()
    )


def run_doctor(workspace: str | Path | None = None) -> dict[str, Any]:
    root = (
        Path(workspace).expanduser().resolve()
        if workspace is not None
        else workspace_root()
    )
    if workspace is not None and not os.environ.get("RESEARCH_AGENT_DB_PATH"):
        state_dir = os.environ.get("RESEARCH_AGENT_STATE_DIR")
        database = (
            Path(state_dir).expanduser() / "state.db"
            if state_dir
            else root / ".research-agent" / "state.db"
        ).resolve()
    else:
        database = state_db_path().resolve()

    import_errors: dict[str, str] = {}
    for module_name in CORE_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - defensive dependency report
            import_errors[module_name] = f"{type(exc).__name__}: {exc}"

    plugin = _codex_plugin_status()
    project_hooks = _project_hook_config(root)
    hook_trusted = _trusted_claudescientist_hooks()
    hook_configured = project_hooks or bool(plugin.get("enabled"))
    intervention_ok = hook_configured and hook_trusted

    checks = {
        "workspace": {
            "status": "ok" if root.is_dir() else "error",
            "path": str(root),
            "writable": os.access(root, os.W_OK) if root.exists() else False,
        },
        "state_database": {
            "status": "ok",
            "path": str(database),
            "exists": database.is_file(),
        },
        "core_imports": {
            "status": "ok" if not import_errors else "error",
            "errors": import_errors,
        },
        "codex_plugin": {
            "status": "ok" if plugin.get("enabled") else "degraded",
            **plugin,
        },
        "hook_delivery": {
            "status": "ok" if intervention_ok else "degraded",
            "configured": hook_configured,
            "trusted": hook_trusted,
            "detail": (
                "Cockpit interventions can be delivered on the next Codex hook event."
                if intervention_ok
                else (
                    "Cockpit remains monitor-only until plugin or project hooks "
                    "are enabled and trusted."
                )
            ),
        },
        "cockpit_monitoring": {
            "status": "ok" if not import_errors else "error",
            "database": str(database),
        },
    }
    statuses = {check["status"] for check in checks.values()}
    overall = "error" if "error" in statuses else ("degraded" if "degraded" in statuses else "ok")
    return {"overall": overall, "checks": checks}


__all__ = ["run_doctor"]
