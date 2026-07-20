"""Installation and workspace diagnostics for ClaudeScientist."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from . import __version__
from .codex_cli import codex_command_prefix, codex_home
from .runtime import installation_root, state_db_path, workspace_root
from .workspace_config import configured_environment, read_workspace_config

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


def _module_errors() -> dict[str, str]:
    errors: dict[str, str] = {}
    for module_name in CORE_IMPORTS:
        try:
            available = importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError) as exc:
            errors[module_name] = f"{type(exc).__name__}: {exc}"
            continue
        if not available:
            errors[module_name] = "module not found"
    return errors


def _project_mcp_enabled(root: Path, server_name: str) -> bool:
    config = _read_toml(root / ".codex" / "config.toml")
    servers = config.get("mcp_servers", {})
    if not isinstance(servers, dict):
        return False
    server = servers.get(server_name)
    if not isinstance(server, dict):
        return False
    return bool(server.get("enabled", True))


def _plugin_mcp_enabled(server_name: str) -> bool:
    """Read user overrides for ClaudeScientist's plugin-provided MCPs."""
    config = _read_toml(codex_home() / "config.toml")
    plugins = config.get("plugins", {})
    if not isinstance(plugins, dict):
        return False
    for plugin_id, plugin in plugins.items():
        if not str(plugin_id).lower().startswith("claudescientist@"):
            continue
        if not isinstance(plugin, dict):
            continue
        servers = plugin.get("mcp_servers", {})
        if not isinstance(servers, dict):
            continue
        server = servers.get(server_name)
        if isinstance(server, dict) and bool(server.get("enabled", True)):
            return True
    return False


def _mcp_enabled(root: Path, server_name: str) -> bool:
    return _project_mcp_enabled(root, server_name) or _plugin_mcp_enabled(server_name)


def _optional_runtime_checks(
    root: Path, *, plugin_managed_dependencies: bool = False
) -> dict[str, dict[str, Any]]:
    node_path = shutil.which("node")
    npm_path = shutil.which("npm") or shutil.which("npm.cmd")
    npx_path = shutil.which("npx") or shutil.which("npx.cmd")
    uv_path = shutil.which("uv") or shutil.which("uv.exe")

    arxiv_enabled = _mcp_enabled(root, "arxiv")
    openalex_enabled = _mcp_enabled(root, "openalex")
    lean_mcp_enabled = _mcp_enabled(root, "lean")
    lean_requested = os.environ.get("RESEARCH_AGENT_LEAN_ENABLED", "").strip().lower()
    lean_workspace_enabled = (
        lean_requested in {"1", "true", "yes", "on"}
        if lean_requested
        else lean_mcp_enabled
    )

    lean_tools = {
        name: shutil.which(name)
        for name in ("elan", "lake", "lean")
    }
    lean_ready = all(lean_tools.values())
    lean_project_value = os.environ.get("LEAN_PROJECT_PATH", "").strip()
    lean_project = Path(lean_project_value) if lean_project_value else None
    lean_project_ready = bool(
        lean_project is not None and (lean_project / "lakefile.lean").is_file()
    )
    lean_active = lean_mcp_enabled and lean_workspace_enabled
    lean_complete = lean_ready and lean_project_ready

    backend = os.environ.get("RESEARCH_AGENT_EMBED_BACKEND", "local").strip().lower()
    model = os.environ.get("RESEARCH_AGENT_EMBED_MODEL", "")
    if backend == "mock":
        embedding_ready = True
        current_process_ready = True
        embedding_detail = "Deterministic mock backend selected."
    elif backend == "local":
        current_process_ready = (
            importlib.util.find_spec("sentence_transformers") is not None
        )
        embedding_ready = current_process_ready or plugin_managed_dependencies
        embedding_detail = (
            "Local sentence-transformers backend is importable."
            if current_process_ready
            else (
                "The public plugin resolves the proof dependencies in its pinned "
                "prove MCP environment."
                if plugin_managed_dependencies
                else "Install the proof extra or select another embedding backend."
            )
        )
    elif backend == "openai":
        client_ready = importlib.util.find_spec("openai") is not None
        credential_present = bool(os.environ.get("OPENAI_API_KEY"))
        current_process_ready = client_ready and credential_present
        embedding_ready = (
            client_ready or plugin_managed_dependencies
        ) and credential_present
        embedding_detail = (
            "OpenAI-compatible client and credential are present."
            if current_process_ready
            else (
                "The plugin provides the client, but OPENAI_API_KEY is still required."
                if plugin_managed_dependencies and not credential_present
                else "The OpenAI-compatible backend needs the client and OPENAI_API_KEY."
            )
        )
    else:
        embedding_ready = False
        current_process_ready = False
        embedding_detail = f"Unknown embedding backend: {backend!r}."

    return {
        "node_runtime": {
            "status": "ok" if node_path and npm_path and npx_path else "optional",
            "node": node_path,
            "npm": npm_path,
            "npx": npx_path,
            "detail": "Required only for the opt-in OpenAlex MCP.",
        },
        "literature_arxiv": {
            "status": "ok" if (uv_path or not arxiv_enabled) else "degraded",
            "enabled": arxiv_enabled,
            "launcher": uv_path,
            "version_pin": "arxiv-mcp-server==0.5.0",
            "network_checked": False,
        },
        "literature_openalex": {
            "status": (
                "ok"
                if (node_path and npm_path and npx_path) or not openalex_enabled
                else "degraded"
            ),
            "enabled": openalex_enabled,
            "launcher": npx_path,
            "version_pin": "openalex-research-mcp@0.5.0",
            "network_checked": False,
        },
        "lean_reinsurance": {
            "status": "ok" if lean_complete or not lean_active else "degraded",
            "enabled": lean_active,
            "mcp_enabled": lean_mcp_enabled,
            "workspace_enabled": lean_workspace_enabled,
            "ready": lean_complete,
            "tools": lean_tools,
            "project_path": str(lean_project) if lean_project else None,
            "project_ready": lean_project_ready,
            "detail": (
                "Lean is ready for this workspace."
                if lean_complete and lean_active
                else "Lean is optional; the natural-language proof trunk remains usable."
            ),
        },
        "embedding_backend": {
            "status": "ok" if embedding_ready else "degraded",
            "backend": backend,
            "model": model or None,
            "ready": embedding_ready,
            "current_process_ready": current_process_ready,
            "plugin_managed_dependencies": plugin_managed_dependencies,
            "detail": embedding_detail,
        },
    }


def run_doctor(workspace: str | Path | None = None) -> dict[str, Any]:
    root = (
        Path(workspace).expanduser().resolve()
        if workspace is not None
        else workspace_root()
    )
    loaded = read_workspace_config(root)
    with configured_environment(root):
        return _run_doctor(root, loaded)


def _run_doctor(root: Path, loaded_config) -> dict[str, Any]:
    if not os.environ.get("RESEARCH_AGENT_DB_PATH"):
        state_dir = os.environ.get("RESEARCH_AGENT_STATE_DIR")
        database = (
            Path(state_dir).expanduser() / "state.db"
            if state_dir
            else root / ".research-agent" / "state.db"
        ).resolve()
    else:
        database = state_db_path().resolve()

    import_errors = _module_errors()

    plugin = _codex_plugin_status()
    plugin_versions = [str(version) for version in plugin.get("versions", [])]
    plugin_version_match = not plugin_versions or __version__ in plugin_versions
    plugin_enabled = bool(plugin.get("enabled"))
    project_hooks = _project_hook_config(root)
    hook_trusted = _trusted_claudescientist_hooks()
    hook_configured = project_hooks or bool(plugin.get("enabled"))
    intervention_ok = hook_configured and hook_trusted
    install_root = installation_root().resolve()
    database_in_installation = database.is_relative_to(install_root)
    misplaced_database = database_in_installation and root != install_root

    checks = {
        "workspace": {
            "status": "ok" if root.is_dir() else "error",
            "path": str(root),
            "writable": os.access(root, os.W_OK) if root.exists() else False,
        },
        "workspace_configuration": {
            "status": "error" if loaded_config.errors else (
                "ok" if loaded_config.exists else "degraded"
            ),
            "path": str(loaded_config.path),
            "exists": loaded_config.exists,
            "errors": list(loaded_config.errors),
            "detail": (
                "Run `claudescientist configure --workspace .` in this project."
                if not loaded_config.exists
                else "Workspace configuration loaded."
            ),
        },
        "state_database": {
            "status": "error" if misplaced_database else "ok",
            "path": str(database),
            "exists": database.is_file(),
            "installation_root": str(install_root),
            "inside_installation_root": database_in_installation,
            "misplaced": misplaced_database,
        },
        "python_package": {
            "status": "ok",
            "version": __version__,
            "installation_root": str(install_root),
        },
        "core_imports": {
            "status": "ok" if not import_errors else "error",
            "errors": import_errors,
        },
        "codex_plugin": {
            "status": "ok" if plugin_enabled and plugin_version_match else "degraded",
            **plugin,
            "version_match": plugin_version_match,
            "expected_version": __version__,
            "detail": (
                f"Installed plugin version {', '.join(plugin_versions)} does not "
                f"match Python package {__version__}."
                if plugin_enabled and not plugin_version_match
                else plugin.get("detail", "")
            ),
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
        **_optional_runtime_checks(
            root,
            plugin_managed_dependencies=plugin_enabled and plugin_version_match,
        ),
    }
    statuses = {check["status"] for check in checks.values()}
    overall = "error" if "error" in statuses else ("degraded" if "degraded" in statuses else "ok")
    return {"overall": overall, "checks": checks}


__all__ = ["run_doctor"]
